import io

from unittest import TestCase

from parameterized import parameterized

from posthog.settings.utils import is_interactive_shell


class _Stdin(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class TestIsInteractiveShell(TestCase):
    @parameterized.expand(
        [
            ("shell", ["manage.py", "shell"], True, True),
            ("dbshell", ["manage.py", "dbshell"], True, True),
            ("shell_with_command", ["manage.py", "shell", "-c", "print(1)"], True, False),
            ("shell_with_long_command", ["manage.py", "shell", "--command=print(1)"], True, False),
            ("shell_with_piped_stdin", ["manage.py", "shell"], False, False),
            ("shell_plus", ["manage.py", "shell_plus"], True, False),
            ("runserver", ["manage.py", "runserver"], True, False),
            ("no_subcommand", ["manage.py"], True, False),
        ]
    )
    def test_only_a_prompt_counts_as_interactive(self, _name, argv, tty, expected) -> None:
        assert is_interactive_shell(argv, _Stdin(tty)) is expected

    def test_a_closed_stdin_is_not_a_prompt(self) -> None:
        stdin = io.StringIO()
        stdin.close()

        assert is_interactive_shell(["manage.py", "shell"], stdin) is False
