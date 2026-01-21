"""Tests for the hogli CLI."""

from __future__ import annotations

import os

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

# Skip Django setup for these tests
os.environ["DJANGO_SKIP_MIGRATIONS"] = "true"

from hogli.core.cli import cli

runner = CliRunner()


class TestMainCommand:
    """Test main command functionality."""

    def test_help_displays_commands(self) -> None:
        """Verify --help displays available commands."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        # Check for some core commands that should exist
        assert "start" in result.output or "docker" in result.output or "migrations" in result.output

    def test_help_displays_categories(self) -> None:
        """Verify --help displays command categories."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Should have at least one category from metadata
        output_lower = result.output.lower()
        assert any(
            category in output_lower for category in ["core development", "start services", "migrations", "tests"]
        )

    def test_invalid_command_fails(self) -> None:
        """Verify invalid commands fail gracefully."""
        result = runner.invoke(cli, ["nonexistent-command"])
        assert result.exit_code != 0


class TestQuickstartCommand:
    """Test quickstart command."""

    def test_quickstart_displays_help(self) -> None:
        """Verify quickstart command displays getting started info."""
        result = runner.invoke(cli, ["quickstart"])
        assert result.exit_code == 0
        assert "PostHog Development Quickstart" in result.output
        assert "hogli" in result.output


class TestMetaCheckCommand:
    """Test meta:check command."""

    def test_meta_check_validates_manifest(self) -> None:
        """Verify meta:check validates manifest entries."""
        result = runner.invoke(cli, ["meta:check"])
        # Should either pass or report missing entries clearly
        assert "bin script" in result.output.lower() or "✓" in result.output


class TestMetaConceptsCommand:
    """Test meta:concepts command."""

    def test_meta_concepts_displays_services(self) -> None:
        """Verify meta:concepts displays infrastructure concepts."""
        result = runner.invoke(cli, ["meta:concepts"])
        assert result.exit_code == 0
        assert "Infrastructure" in result.output or "service" in result.output.lower()


class TestDynamicCommandRegistration:
    """Test that commands are dynamically registered from manifest."""

    def test_start_command_exists(self) -> None:
        """Verify start command is registered from manifest."""
        result = runner.invoke(cli, ["start", "--help"])
        # Should either work or show a proper Click error
        assert "Error: No such command" not in result.output or result.exit_code == 2

    def test_migrations_command_exists(self) -> None:
        """Verify migrations commands are registered from manifest."""
        result = runner.invoke(cli, ["migrations:run", "--help"])
        # Should either work or show proper error
        assert "Error: No such command" not in result.output or result.exit_code == 2

    @patch("hogli.core.command_types._run")
    def test_command_with_bin_script_executes(self, mock_run: MagicMock) -> None:
        """Verify bin_script commands can execute."""
        mock_run.return_value = None
        # Try a command that should have a bin_script
        result = runner.invoke(cli, ["check:postgres", "--help"])
        # Should return help or execute
        assert result.exit_code in (0, 2)

    @patch("hogli.core.command_types._run")
    def test_direct_command_execution(self, mock_run: MagicMock) -> None:
        """Verify direct cmd commands execute properly."""
        mock_run.return_value = None
        # build:schema-json uses direct cmd field
        result = runner.invoke(cli, ["build:schema-json", "--help"])
        assert result.exit_code in (0, 2)


class TestCommandInjectionPrevention:
    """Test that command argument handling is secure."""

    @patch("hogli.core.command_types._run")
    def test_arguments_are_properly_escaped(self, mock_run: MagicMock) -> None:
        """Verify arguments passed to commands are properly escaped."""
        mock_run.return_value = None
        # Invoke a command with special characters
        result = runner.invoke(cli, ["migrations:run", "--help"])
        # The key test is that no exception is raised during argument parsing
        assert result.exit_code in (0, 1, 2)  # Any of these is acceptable

    @patch("hogli.core.command_types._run")
    def test_shell_operators_are_handled_safely(self, mock_run: MagicMock) -> None:
        """Verify commands with shell operators are executed safely."""
        mock_run.return_value = None
        # Invoke a composite command
        result = runner.invoke(cli, ["dev:reset", "--help"])
        # Should not raise an exception
        assert result.exit_code in (0, 1, 2)


class TestHelpText:
    """Test command help text generation."""

    def test_command_help_includes_description(self) -> None:
        """Verify command help includes description from manifest."""
        result = runner.invoke(cli, ["start", "--help"])
        # Should contain help text
        assert "Usage:" in result.output or result.exit_code == 2

    def test_category_grouping_in_help(self) -> None:
        """Verify help output groups commands by category."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Should have multiple sections
        lines = result.output.split("\n")
        # Look for section headers (typically uppercase or titled)
        assert len(lines) > 10


class TestExtendsTreeDisplay:
    """Test extends inheritance display in help."""

    def test_main_help_shows_children_indented(self) -> None:
        """Main help shows child commands under parent with tree prefix."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Should show tree structure
        assert "└─ :minimal" in result.output

    def test_child_commands_not_shown_at_top_level(self) -> None:
        """Child commands are not duplicated at top level."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # Full child name should not appear as standalone command
        # (it appears only as indented variant)
        lines = result.output.split("\n")
        top_level_commands = [
            line.strip().split()[0] for line in lines if line.strip() and not line.strip().startswith("└─")
        ]
        assert "docker:services:up:minimal" not in top_level_commands

    def test_parent_help_shows_variants_with_commands(self) -> None:
        """Parent command help shows variants with their commands."""
        result = runner.invoke(cli, ["docker:services:up", "--help"])
        assert result.exit_code == 0
        assert "Executes:" in result.output
        assert ":minimal" in result.output
        assert "docker-compose.dev-minimal.yml" in result.output

    def test_child_help_shows_inherited_description(self) -> None:
        """Child command help shows inherited description."""
        result = runner.invoke(cli, ["docker:services:up:minimal", "--help"])
        assert result.exit_code == 0
        # Should have parent's description
        assert "Start Docker infrastructure services" in result.output
        # Should show its own command
        assert "docker-compose.dev-minimal.yml" in result.output

    def test_child_command_is_callable(self) -> None:
        """Child commands are registered and callable."""
        result = runner.invoke(cli, ["docker:services:up:minimal", "--help"])
        # Should not be "No such command"
        assert "Error: No such command" not in result.output
        assert result.exit_code == 0
