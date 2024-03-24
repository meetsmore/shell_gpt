import json
import platform
from enum import Enum
from os import getenv, pathsep
from os.path import basename
from pathlib import Path
from typing import Dict, Optional

import typer
from click import BadArgumentUsage
from distro import name as distro_name

from .config import cfg
from .utils import option_callback

SHELL_ROLE = """Provide only {shell} commands for {os} without any description.
If there is a lack of details, provide most logical solution.
Ensure the output is a valid shell command.
If multiple steps required try to combine them together using &&.
Provide only plain text without Markdown formatting.
Do not provide markdown formatting such as ```.
"""

DESCRIBE_SHELL_ROLE = """Provide a terse, single sentence description of the given shell command.
Describe each argument and option of the command.
Provide short responses in about 80 words.
APPLY MARKDOWN formatting when possible."""
# Note that output for all roles containing "APPLY MARKDOWN" will be formatted as Markdown.

CODE_ROLE = """Provide only code as output without any description.
Provide only code in plain text format without Markdown formatting.
Do not include symbols such as ``` or ```python.
If there is a lack of details, provide most logical solution.
You are not allowed to ask for more details.
For example if the prompt is "Hello world Python", you should return "print('Hello world')"."""

DEFAULT_ROLE = """You are programming and system administration assistant.
You are managing {os} operating system with {shell} shell.
Provide short responses in about 100 words, unless you are specifically asked for more details.
If you need to store any data, assume it will be stored in the conversation.
APPLY MARKDOWN formatting when possible."""
# Note that output for all roles containing "APPLY MARKDOWN" will be formatted as Markdown.

def role_template(name: str, role: str, message_to_role: str) -> str:
    if message_to_role:
        return f"{role}"
    else:
        return f"You are {name}\n{role}"

class SystemRole:
    storage: Path = Path(cfg.get("ROLE_STORAGE_PATH"))

    """
    Inside of a role.json file:
    "message_to_role": {
		"phrase": "あなたの任務は、日本語から英語",
		"name": "jp-to-en"
	}

    After being loaded into message_to_role:
    {
        "あなたの任務は、日本語から英語": "jp-to-en"
    }
    """
    message_to_role: Dict[str, str] = {}

    def __init__(
        self,
        name: str,
        role: str,
        message_to_role: Optional[Dict[str, str]] = None,
        variables: Optional[Dict[str, str]] = None,
    ) -> None:
        self.storage.mkdir(parents=True, exist_ok=True)
        self.name = name
        if variables:
            role = role.format(**variables)
        self.role = role
        self.message_to_role = message_to_role

    @classmethod
    def create_defaults(cls) -> None:
        cls.storage.parent.mkdir(parents=True, exist_ok=True)
        variables = {"shell": cls._shell_name(), "os": cls._os_name()}
        for default_role in (
            SystemRole("ShellGPT", DEFAULT_ROLE, variables),
            SystemRole("Shell Command Generator", SHELL_ROLE, variables),
            SystemRole("Shell Command Descriptor", DESCRIBE_SHELL_ROLE, variables),
            SystemRole("Code Generator", CODE_ROLE),
        ):
            if not default_role._exists:
                default_role._save()

        for file in cls.storage.iterdir():
            if file.is_file() and file.name.endswith(".json"):
                # read file
                role = json.loads(file.read_text())
                # load message_to_role mappings
                message_to_role = role.get("message_to_role")

                if message_to_role:
                    cls.message_to_role[message_to_role["phrase"]] = message_to_role["name"]

    @classmethod
    def get(cls, name: str) -> "SystemRole":
        file_path = cls.storage / f"{name}.json"
        if not file_path.exists():
            raise BadArgumentUsage(f'Role "{name}" not found.')
        return cls(**json.loads(file_path.read_text()))

    @classmethod
    @option_callback
    def create(cls, name: str) -> None:
        role = typer.prompt("Enter role description")
        role = cls(name, role)
        role._save()

    @classmethod
    @option_callback
    def list(cls, _value: str) -> None:
        if not cls.storage.exists():
            return
        # Get all files in the folder.
        files = cls.storage.glob("*")
        # Sort files by last modification time in ascending order.
        for path in sorted(files, key=lambda f: f.stat().st_mtime):
            typer.echo(path)

    @classmethod
    @option_callback
    def show(cls, name: str) -> None:
        typer.echo(cls.get(name).role)

    @classmethod
    def get_role_name(cls, initial_message: str) -> Optional[str]:
        if not initial_message:
            return None

        message_lines = initial_message.splitlines()

        # skip the initial "system: "
        first_twenty_lines = message_lines[0][8:27]

        if "You are" in message_lines[0]:
            return message_lines[0].split("You are ")[1].strip()
        elif cls.message_to_role.get(first_twenty_lines):
            return cls.message_to_role[first_twenty_lines]

        return None

    @classmethod
    def _os_name(cls) -> str:
        current_platform = platform.system()
        if current_platform == "Linux":
            return "Linux/" + distro_name(pretty=True)
        if current_platform == "Windows":
            return "Windows " + platform.release()
        if current_platform == "Darwin":
            return "Darwin/MacOS " + platform.mac_ver()[0]
        return current_platform

    @classmethod
    def _shell_name(cls) -> str:
        current_platform = platform.system()
        if current_platform in ("Windows", "nt"):
            is_powershell = len(getenv("PSModulePath", "").split(pathsep)) >= 3
            return "powershell.exe" if is_powershell else "cmd.exe"
        return basename(getenv("SHELL", "/bin/sh"))

    @property
    def _exists(self) -> bool:
        return self._file_path.exists()

    @property
    def _file_path(self) -> Path:
        return self.storage / f"{self.name}.json"

    def _save(self) -> None:
        if self._exists:
            typer.confirm(
                f'Role "{self.name}" already exists, overwrite it?',
                abort=True,
            )

        """
        Use first 20 characters as the mapping from message to role
        so that we don't have to rely on shell_gpt's existing hardcoded
        "You are" prefix to determine the role
        """
        message_to_role = self.role[:20]

        self.role = role_template(name=self.name, role=self.role, message_to_role=message_to_role)
        self._file_path.write_text(json.dumps(self.__dict__, ensure_ascii=False), encoding="utf-8")

    def delete(self) -> None:
        if self._exists:
            typer.confirm(
                f'Role "{self.name}" exist, delete it?',
                abort=True,
            )
        self._file_path.unlink()

    def same_role(self, initial_message: str) -> bool:
        if not initial_message:
            return False
        return True if f"You are {self.name}" in initial_message else False


class DefaultRoles(Enum):
    DEFAULT = "ShellGPT"
    SHELL = "Shell Command Generator"
    DESCRIBE_SHELL = "Shell Command Descriptor"
    CODE = "Code Generator"

    @classmethod
    def check_get(cls, shell: bool, describe_shell: bool, code: bool) -> SystemRole:
        if shell:
            return SystemRole.get(DefaultRoles.SHELL.value)
        if describe_shell:
            return SystemRole.get(DefaultRoles.DESCRIBE_SHELL.value)
        if code:
            return SystemRole.get(DefaultRoles.CODE.value)
        return SystemRole.get(DefaultRoles.DEFAULT.value)

    def get_role(self) -> SystemRole:
        return SystemRole.get(self.value)


SystemRole.create_defaults()
