"""Tests for command type execution - critical paths only."""

from __future__ import annotations

import subprocess

import pytest
from unittest.mock import MagicMock, patch

from hogli.core.command_types import CompositeCommand, DirectCommand


class TestDirectCommandExecution:
    """Test DirectCommand handles shell operators and arguments correctly."""

    @patch("hogli.core.command_types._run")
    def test_handles_shell_operators_with_shell_true(self, mock_run: MagicMock) -> None:
        """Test commands with && or || use shell=True."""
        cmd = DirectCommand("test", {"cmd": "echo foo && echo bar"})

        cmd.execute()

        # Should call _run with shell=True for shell operators
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == "echo foo && echo bar"
        assert call_args[1]["shell"] is True

    @patch("hogli.core.command_types._run")
    def test_handles_simple_commands_without_shell(self, mock_run: MagicMock) -> None:
        """Test simple commands without operators use list format."""
        cmd = DirectCommand("test", {"cmd": "pytest tests/"})

        cmd.execute()

        # Should call _run with list format (no shell)
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert isinstance(call_args[0][0], list)
        assert call_args[0][0] == ["pytest", "tests/"]

    @patch("hogli.core.command_types._run")
    def test_appends_extra_args_to_shell_commands(self, mock_run: MagicMock) -> None:
        """Test extra args are safely escaped and appended to shell commands."""
        cmd = DirectCommand("test", {"cmd": "echo foo && echo bar"})

        cmd.execute("arg1", "arg with spaces")

        # Args should be shell-escaped and appended
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd_str = call_args[0][0]
        assert "arg1" in cmd_str
        assert "'arg with spaces'" in cmd_str or '"arg with spaces"' in cmd_str

    @patch("hogli.core.command_types._run")
    def test_appends_extra_args_to_simple_commands(self, mock_run: MagicMock) -> None:
        """Test extra args are appended to list-format commands."""
        cmd = DirectCommand("test", {"cmd": "pytest"})

        cmd.execute("test_file.py", "--verbose")

        # Args should be in list
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["pytest", "test_file.py", "--verbose"]


class TestCompositeCommandExecution:
    """Test CompositeCommand runs steps sequentially and handles failures."""

    @patch("hogli.core.command_types._run")
    def test_executes_all_steps_in_sequence(self, mock_run: MagicMock) -> None:
        """Test all steps are executed in order."""
        from hogli.core.manifest import REPO_ROOT

        bin_hogli = str(REPO_ROOT / "bin" / "hogli")

        cmd = CompositeCommand(
            "reset",
            {"steps": ["docker:services:down", "docker:services:up", "migrations:run"]},
        )

        cmd.execute()

        assert mock_run.call_count == 3
        calls = [call[0][0] for call in mock_run.call_args_list]
        assert calls == [
            [bin_hogli, "docker:services:down"],
            [bin_hogli, "docker:services:up"],
            [bin_hogli, "migrations:run"],
        ]

    @patch("hogli.core.command_types._run")
    def test_stops_on_first_failure(self, mock_run: MagicMock) -> None:
        """Test execution stops when a step fails."""
        mock_run.side_effect = [None, SystemExit(1), None]  # Second step fails

        cmd = CompositeCommand("reset", {"steps": ["step1", "step2", "step3"]})

        with pytest.raises(SystemExit):
            cmd.execute()

        # Should only call first two steps before failure
        assert mock_run.call_count == 2

    @patch("hogli.core.command_types._run")
    def test_inline_steps_execute_directly(self, mock_run: MagicMock) -> None:
        """Test inline dict steps execute as shell commands."""
        from hogli.core.manifest import REPO_ROOT

        bin_hogli = str(REPO_ROOT / "bin" / "hogli")

        cmd = CompositeCommand(
            "nuke",
            {
                "steps": [
                    {"name": "announce", "cmd": "echo hello"},
                    {"name": "cleanup", "cmd": "rm -rf /tmp/test"},
                    "dev:reset",
                ]
            },
        )

        cmd.execute()

        assert mock_run.call_count == 3
        # First two are inline shell commands
        assert mock_run.call_args_list[0][0][0] == ["bash", "-c", "echo hello"]
        assert mock_run.call_args_list[1][0][0] == ["bash", "-c", "rm -rf /tmp/test"]
        # Third is a hogli command
        assert mock_run.call_args_list[2][0][0] == [bin_hogli, "dev:reset"]


class TestRunFunctionErrorHandling:
    """Test _run() handles command failures correctly."""

    def test_run_raises_systemexit_on_command_failure(self) -> None:
        """Test _run raises SystemExit when subprocess fails."""
        from hogli.core.command_types import _run

        # Command that will fail
        with pytest.raises(SystemExit) as exc_info:
            _run(["false"])  # 'false' command always returns exit code 1

        assert exc_info.value.code == 1

    @patch("subprocess.run")
    def test_run_handles_called_process_error(self, mock_subprocess: MagicMock) -> None:
        """Test _run converts CalledProcessError to SystemExit."""
        from hogli.core.command_types import _run

        mock_subprocess.side_effect = subprocess.CalledProcessError(1, "cmd")

        with pytest.raises(SystemExit) as exc_info:
            _run(["some-command"])

        assert exc_info.value.code == 1


class TestConfirmationFeature:
    """Test confirmation prompts using prompt: true/string."""

    @patch("click.confirm")
    @patch("hogli.core.command_types._run")
    def test_prompt_true_shows_warning(self, mock_run: MagicMock, mock_confirm: MagicMock) -> None:
        """Test prompt: true shows destructive warning."""
        mock_confirm.return_value = True

        cmd = DirectCommand("test:dangerous", {"cmd": "rm -rf /", "prompt": True})

        cmd._confirm(yes=False)

        mock_confirm.assert_called_once_with("Are you sure you want to continue?", default=False)

    @patch("click.confirm")
    @patch("hogli.core.command_types._run")
    def test_prompt_string_shows_custom_question(self, mock_run: MagicMock, mock_confirm: MagicMock) -> None:
        """Test prompt: string shows custom question."""
        mock_confirm.return_value = True

        cmd = DirectCommand("test:optional", {"cmd": "echo hi", "prompt": "Run this?"})

        cmd._confirm(yes=False)

        mock_confirm.assert_called_once_with("Run this?", default=False)

    @patch("click.confirm")
    @patch("hogli.core.command_types._run")
    def test_prompt_skips_with_yes_flag(self, mock_run: MagicMock, mock_confirm: MagicMock) -> None:
        """Test --yes flag skips confirmation prompt."""
        cmd = DirectCommand("test:dangerous", {"cmd": "rm -rf /", "prompt": True})

        cmd._confirm(yes=True)

        mock_confirm.assert_not_called()

    @patch("click.confirm")
    @patch("hogli.core.command_types._run")
    def test_no_confirmation_without_prompt(self, mock_run: MagicMock, mock_confirm: MagicMock) -> None:
        """Test commands without prompt don't ask."""
        cmd = DirectCommand("test:safe", {"cmd": "echo hello"})

        cmd._confirm(yes=False)

        mock_confirm.assert_not_called()

    @patch("click.confirm")
    @patch("hogli.core.command_types._run")
    def test_confirmation_abort_exits_gracefully(self, mock_run: MagicMock, mock_confirm: MagicMock) -> None:
        """Test aborting confirmation exits with code 0."""
        mock_confirm.return_value = False

        cmd = DirectCommand("test:dangerous", {"cmd": "rm -rf /", "prompt": True})

        with pytest.raises(SystemExit) as exc_info:
            cmd._confirm(yes=False)

        assert exc_info.value.code == 0
        mock_run.assert_not_called()

    @patch("hogli.core.command_types._run")
    def test_composite_command_passes_yes_flag_to_steps(self, mock_run: MagicMock) -> None:
        """Test CompositeCommand passes --yes to child commands when confirmed."""
        from hogli.core.manifest import REPO_ROOT

        bin_hogli = str(REPO_ROOT / "bin" / "hogli")

        cmd = CompositeCommand(
            "reset",
            {"steps": ["docker:services:down", "docker:services:up"], "prompt": True},
        )
        cmd._confirmed = True

        cmd.execute()

        assert mock_run.call_count == 2
        calls = [call[0][0] for call in mock_run.call_args_list]
        assert calls == [
            [bin_hogli, "docker:services:down", "--yes"],
            [bin_hogli, "docker:services:up", "--yes"],
        ]

    @patch("click.confirm")
    @patch("hogli.core.command_types._run")
    def test_composite_command_passes_yes_after_user_confirms(
        self, mock_run: MagicMock, mock_confirm: MagicMock
    ) -> None:
        """Test CompositeCommand passes --yes to children after user confirms via prompt."""
        from hogli.core.manifest import REPO_ROOT

        bin_hogli = str(REPO_ROOT / "bin" / "hogli")
        mock_confirm.return_value = True

        cmd = CompositeCommand(
            "reset",
            {"steps": ["docker:services:down"], "prompt": True},
        )
        # Simulate user confirming via prompt (not --yes flag)
        confirmed = cmd._confirm(yes=False)
        cmd._confirmed = confirmed

        cmd.execute()

        # Should pass --yes to child even though user didn't pass --yes flag
        mock_run.assert_called_once_with([bin_hogli, "docker:services:down", "--yes"], env={})


class TestPromptStep:
    """Test prompt steps with conditional execution using hogli: format."""

    @patch("click.confirm")
    @patch("hogli.core.command_types._run")
    def test_prompt_runs_hogli_when_confirmed(self, mock_run: MagicMock, mock_confirm: MagicMock) -> None:
        """Prompt guard runs hogli command when user says yes."""
        from hogli.core.manifest import REPO_ROOT

        bin_hogli = str(REPO_ROOT / "bin" / "hogli")
        mock_confirm.return_value = True

        cmd = CompositeCommand(
            "test",
            {
                "steps": [
                    {
                        "hogli": "db:restore-schema",
                        "prompt": "Restore schema?",
                        "else": "migrations:run",
                    }
                ]
            },
        )
        cmd.execute()

        mock_confirm.assert_called_once_with("Restore schema?", default=False)
        mock_run.assert_called_once_with([bin_hogli, "db:restore-schema"], env={})

    @patch("click.confirm")
    @patch("hogli.core.command_types._run")
    def test_prompt_runs_else_when_declined(self, mock_run: MagicMock, mock_confirm: MagicMock) -> None:
        """Prompt guard runs else branch when user says no."""
        from hogli.core.manifest import REPO_ROOT

        bin_hogli = str(REPO_ROOT / "bin" / "hogli")
        mock_confirm.return_value = False

        cmd = CompositeCommand(
            "test",
            {
                "steps": [
                    {
                        "hogli": "db:restore-schema",
                        "prompt": "Restore schema?",
                        "else": "migrations:run",  # string shorthand
                    }
                ]
            },
        )
        cmd.execute()

        mock_confirm.assert_called_once_with("Restore schema?", default=False)
        mock_run.assert_called_once_with([bin_hogli, "migrations:run"], env={})

    @patch("click.confirm")
    @patch("hogli.core.command_types._run")
    def test_prompt_skips_when_declined_without_else(self, mock_run: MagicMock, mock_confirm: MagicMock) -> None:
        """Prompt guard skips when user says no and no else provided."""
        mock_confirm.return_value = False

        cmd = CompositeCommand(
            "test",
            {"steps": [{"hogli": "optional:thing", "prompt": "Run optional step?"}]},
        )
        cmd.execute()

        mock_confirm.assert_called_once()
        mock_run.assert_not_called()

    @patch("hogli.core.command_types._run")
    def test_hogli_without_prompt_runs_directly(self, mock_run: MagicMock) -> None:
        """hogli: without prompt runs the command directly."""
        from hogli.core.manifest import REPO_ROOT

        bin_hogli = str(REPO_ROOT / "bin" / "hogli")

        cmd = CompositeCommand(
            "test",
            {"steps": [{"hogli": "migrations:run"}]},
        )
        cmd.execute()

        mock_run.assert_called_once_with([bin_hogli, "migrations:run"], env={})

    @patch("hogli.core.command_types._run")
    def test_string_step_equivalent_to_hogli(self, mock_run: MagicMock) -> None:
        """String step is equivalent to hogli: step."""
        from hogli.core.manifest import REPO_ROOT

        bin_hogli = str(REPO_ROOT / "bin" / "hogli")

        # Both should produce identical calls
        cmd1 = CompositeCommand("test1", {"steps": ["migrations:run"]})
        cmd2 = CompositeCommand("test2", {"steps": [{"hogli": "migrations:run"}]})

        cmd1.execute()
        call1 = mock_run.call_args

        mock_run.reset_mock()

        cmd2.execute()
        call2 = mock_run.call_args

        assert call1 == call2 == (([bin_hogli, "migrations:run"],), {"env": {}})
