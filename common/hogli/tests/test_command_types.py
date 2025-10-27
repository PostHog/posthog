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
        cmd = CompositeCommand(
            "reset",
            {"steps": ["docker:services:down", "docker:services:up", "migrations:run"]},
        )

        cmd.execute()

        assert mock_run.call_count == 3
        calls = [call[0][0] for call in mock_run.call_args_list]
        assert calls == [
            ["hogli", "docker:services:down"],
            ["hogli", "docker:services:up"],
            ["hogli", "migrations:run"],
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
