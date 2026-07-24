from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.management.commands.migrate import Command


class TestMigrateCommandPrompt(SimpleTestCase):
    @parameterized.expand([("keyboard_interrupt", KeyboardInterrupt), ("eof", EOFError)])
    def test_prompt_aborts_cleanly_on_interrupt(self, _name: str, exc: type[BaseException]) -> None:
        command = Command()
        with patch("builtins.input", side_effect=exc):
            with self.assertRaises(SystemExit):
                command._prompt("Continue? ")

    def test_prompt_returns_input(self) -> None:
        command = Command()
        with patch("builtins.input", return_value="y"):
            self.assertEqual(command._prompt("Continue? "), "y")
