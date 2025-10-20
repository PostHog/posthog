"""Tests for the hogli CLI."""

from __future__ import annotations

import os
from pathlib import Path

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

# Skip Django setup for these tests
os.environ["DJANGO_SKIP_MIGRATIONS"] = "true"

from .cli import CommandError, ProductInfo, _discover_products, app

runner = CliRunner()


class TestMainCommand:
    """Test main command functionality."""

    def test_help_displays_all_commands(self) -> None:
        """Verify --help displays all available commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.stdout
        assert "test" in result.stdout
        assert "lint" in result.stdout
        assert "fmt" in result.stdout
        assert "migrate" in result.stdout
        assert "shell" in result.stdout
        assert "build" in result.stdout
        assert "check" in result.stdout
        assert "services" in result.stdout
        assert "worktree" in result.stdout
        assert "products" in result.stdout

    def test_version_flag(self) -> None:
        """Verify --version flag works."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "PostHog hogli" in result.stdout


class TestTestCommand:
    """Test the test command and subcommands."""

    @patch("hogli.cli._run_pytest")
    @patch("hogli.cli._run_jest")
    def test_test_all_scope(self, mock_jest: MagicMock, mock_pytest: MagicMock) -> None:
        """Verify test command runs both pytest and jest with default scope."""
        result = runner.invoke(app, ["test"])
        assert result.exit_code == 0
        mock_pytest.assert_called_once()
        mock_jest.assert_called_once()

    @patch("hogli.cli._run_pytest")
    @patch("hogli.cli._run_jest")
    def test_test_python_scope(self, mock_jest: MagicMock, mock_pytest: MagicMock) -> None:
        """Verify test command with python scope only runs pytest."""
        result = runner.invoke(app, ["test", "--scope", "python"])
        assert result.exit_code == 0
        mock_pytest.assert_called_once()
        mock_jest.assert_not_called()

    @patch("hogli.cli._run_pytest")
    @patch("hogli.cli._run_jest")
    def test_test_js_scope(self, mock_jest: MagicMock, mock_pytest: MagicMock) -> None:
        """Verify test command with js scope only runs jest."""
        result = runner.invoke(app, ["test", "--scope", "js"])
        assert result.exit_code == 0
        mock_pytest.assert_not_called()
        mock_jest.assert_called_once()

    def test_test_invalid_scope(self) -> None:
        """Verify test command rejects invalid scope."""
        result = runner.invoke(app, ["test", "--scope", "invalid"])
        assert result.exit_code != 0

    @patch("hogli.cli._run_pytest")
    def test_test_python_subcommand_with_args(self, mock_pytest: MagicMock) -> None:
        """Verify test python subcommand forwards arguments to pytest."""
        result = runner.invoke(app, ["test", "python", "tests/", "-k", "test_foo"])
        assert result.exit_code == 0
        mock_pytest.assert_called_once_with(["tests/", "-k", "test_foo"])

    @patch("hogli.cli._run_jest")
    def test_test_js_subcommand_with_args(self, mock_jest: MagicMock) -> None:
        """Verify test js subcommand forwards arguments to jest."""
        result = runner.invoke(app, ["test", "js", "frontend/", "--watch"])
        assert result.exit_code == 0
        mock_jest.assert_called_once_with(["frontend/", "--watch"])


class TestLintCommand:
    """Test the lint command."""

    @patch("hogli.cli._run_python_lint")
    @patch("hogli.cli._run_js_lint")
    def test_lint_all_scope(self, mock_js_lint: MagicMock, mock_python_lint: MagicMock) -> None:
        """Verify lint command runs both linters with default scope."""
        result = runner.invoke(app, ["lint"])
        assert result.exit_code == 0
        mock_python_lint.assert_called_once_with(False)
        mock_js_lint.assert_called_once_with(False)

    @patch("hogli.cli._run_python_lint")
    @patch("hogli.cli._run_js_lint")
    def test_lint_fix_flag(self, mock_js_lint: MagicMock, mock_python_lint: MagicMock) -> None:
        """Verify lint command respects --fix flag."""
        result = runner.invoke(app, ["lint", "--fix"])
        assert result.exit_code == 0
        mock_python_lint.assert_called_once_with(True)
        mock_js_lint.assert_called_once_with(True)

    @patch("hogli.cli._run_python_lint")
    @patch("hogli.cli._run_js_lint")
    def test_lint_python_scope(self, mock_js_lint: MagicMock, mock_python_lint: MagicMock) -> None:
        """Verify lint command with python scope only runs python linter."""
        result = runner.invoke(app, ["lint", "--scope", "python"])
        assert result.exit_code == 0
        mock_python_lint.assert_called_once()
        mock_js_lint.assert_not_called()

    def test_lint_invalid_scope(self) -> None:
        """Verify lint command rejects invalid scope."""
        result = runner.invoke(app, ["lint", "--scope", "invalid"])
        assert result.exit_code != 0


class TestFmtCommand:
    """Test the fmt command."""

    @patch("hogli.cli._run_python_fmt")
    @patch("hogli.cli._run_js_fmt")
    def test_fmt_all_scope(self, mock_js_fmt: MagicMock, mock_python_fmt: MagicMock) -> None:
        """Verify fmt command runs both formatters with default scope."""
        result = runner.invoke(app, ["fmt"])
        assert result.exit_code == 0
        mock_python_fmt.assert_called_once()
        mock_js_fmt.assert_called_once()

    @patch("hogli.cli._run_python_fmt")
    @patch("hogli.cli._run_js_fmt")
    def test_fmt_python_scope(self, mock_js_fmt: MagicMock, mock_python_fmt: MagicMock) -> None:
        """Verify fmt command with python scope only runs python formatter."""
        result = runner.invoke(app, ["fmt", "--scope", "python"])
        assert result.exit_code == 0
        mock_python_fmt.assert_called_once()
        mock_js_fmt.assert_not_called()

    def test_fmt_invalid_scope(self) -> None:
        """Verify fmt command rejects invalid scope."""
        result = runner.invoke(app, ["fmt", "--scope", "invalid"])
        assert result.exit_code != 0


class TestBuildCommand:
    """Test the build command."""

    @patch("hogli.cli._run_frontend_build")
    def test_build_default_scope(self, mock_build: MagicMock) -> None:
        """Verify build command runs frontend build with default scope."""
        result = runner.invoke(app, ["build"])
        assert result.exit_code == 0
        mock_build.assert_called_once()

    @patch("hogli.cli._run_frontend_build")
    def test_build_frontend_scope(self, mock_build: MagicMock) -> None:
        """Verify build command with frontend scope runs frontend build."""
        result = runner.invoke(app, ["build", "--scope", "frontend"])
        assert result.exit_code == 0
        mock_build.assert_called_once()

    def test_build_invalid_scope(self) -> None:
        """Verify build command rejects invalid scope."""
        result = runner.invoke(app, ["build", "--scope", "invalid"])
        assert result.exit_code != 0


class TestMigrateCommand:
    """Test the migrate command."""

    @patch("hogli.cli._run")
    def test_migrate_runs_script(self, mock_run: MagicMock) -> None:
        """Verify migrate command executes the migration script."""
        result = runner.invoke(app, ["migrate"])
        assert result.exit_code == 0
        mock_run.assert_called_once()


class TestServicesCommand:
    """Test the services command."""

    @patch("hogli.cli._run")
    def test_services_up_default(self, mock_run: MagicMock) -> None:
        """Verify services command starts infrastructure by default."""
        result = runner.invoke(app, ["services"])
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch("hogli.cli._run")
    def test_services_down(self, mock_run: MagicMock) -> None:
        """Verify services --down flag stops infrastructure."""
        result = runner.invoke(app, ["services", "--down"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        # Check that the command includes "down"
        call_args = mock_run.call_args[0][0]
        assert "down" in call_args

    @patch("hogli.cli._run")
    def test_services_rebuild(self, mock_run: MagicMock) -> None:
        """Verify services --rebuild flag recreates containers."""
        result = runner.invoke(app, ["services", "--rebuild"])
        assert result.exit_code == 0
        mock_run.assert_called_once()


class TestCheckCommand:
    """Test the check command."""

    @patch("hogli.cli._run_python_lint")
    @patch("hogli.cli._run_js_lint")
    @patch("hogli.cli._run_pytest")
    @patch("hogli.cli._run_jest")
    @patch("hogli.cli._run_frontend_build")
    def test_check_runs_all(
        self,
        mock_build: MagicMock,
        mock_jest: MagicMock,
        mock_pytest: MagicMock,
        mock_js_lint: MagicMock,
        mock_python_lint: MagicMock,
    ) -> None:
        """Verify check command runs linting, testing, and building."""
        result = runner.invoke(app, ["check"])
        assert result.exit_code == 0
        mock_python_lint.assert_called_once()
        mock_js_lint.assert_called_once()
        mock_pytest.assert_called_once()
        mock_jest.assert_called_once()
        mock_build.assert_called_once()

    @patch("hogli.cli._run_python_lint")
    @patch("hogli.cli._run_pytest")
    @patch("hogli.cli._run_frontend_build")
    def test_check_skip_linting(self, mock_build: MagicMock, mock_pytest: MagicMock, mock_lint: MagicMock) -> None:
        """Verify check --skip-lint skips linting."""
        result = runner.invoke(app, ["check", "--skip-lint"])
        assert result.exit_code == 0
        mock_lint.assert_not_called()

    @patch("hogli.cli._run_python_lint")
    @patch("hogli.cli._run_js_lint")
    @patch("hogli.cli._run_pytest")
    @patch("hogli.cli._run_frontend_build")
    def test_check_skip_tests(
        self,
        mock_build: MagicMock,
        mock_pytest: MagicMock,
        mock_js_lint: MagicMock,
        mock_python_lint: MagicMock,
    ) -> None:
        """Verify check --skip-tests skips testing."""
        result = runner.invoke(app, ["check", "--skip-tests"])
        assert result.exit_code == 0
        mock_pytest.assert_not_called()


class TestProductsCommand:
    """Test the products command."""

    def test_products_list_help(self) -> None:
        """Verify products list command displays help."""
        result = runner.invoke(app, ["products", "list", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.stdout

    @patch("hogli.cli._discover_products")
    def test_products_list_table_output(self, mock_discover: MagicMock) -> None:
        """Verify products list outputs table by default."""
        mock_discover.return_value = [
            ProductInfo("analytics", "@posthog/analytics", True, True),
            ProductInfo("experiments", "@posthog/experiments", True, False),
        ]
        result = runner.invoke(app, ["products", "list"])
        assert result.exit_code == 0
        assert "analytics" in result.stdout
        assert "experiments" in result.stdout

    @patch("hogli.cli._discover_products")
    def test_products_list_json_output(self, mock_discover: MagicMock) -> None:
        """Verify products list outputs JSON with --json flag."""
        mock_discover.return_value = [
            ProductInfo("analytics", "@posthog/analytics", True, True),
        ]
        result = runner.invoke(app, ["products", "list", "--json"])
        assert result.exit_code == 0
        assert '"slug": "analytics"' in result.stdout


class TestDiscoverProducts:
    """Test product discovery functionality."""

    def test_discover_products_no_directory(self) -> None:
        """Verify _discover_products handles missing products directory."""
        with patch("hogli.cli.REPO_ROOT", Path("/nonexistent")):
            result = _discover_products()
            assert result == []

    def test_discover_products_empty_directory(self, tmp_path: Path) -> None:
        """Verify _discover_products handles empty products directory."""
        with patch("hogli.cli.REPO_ROOT", tmp_path):
            products_dir = tmp_path / "products"
            products_dir.mkdir()
            result = _discover_products()
            assert result == []


class TestErrorHandling:
    """Test error handling in CLI."""

    def test_command_error_message(self) -> None:
        """Verify CommandError displays user-friendly message."""
        error = CommandError("Test error message")
        assert str(error) == "Test error message"
