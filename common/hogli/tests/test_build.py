"""Tests for the hogli build command."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.build import PIPELINES, _get_changed_files, _match_pipelines
from hogli.core.cli import cli

runner = CliRunner()


class TestPipelineMatching:
    @pytest.mark.parametrize(
        "path,expected_pipeline",
        [
            ("frontend/src/queries/schema/index.ts", "schema"),
            ("frontend/src/queries/schema/schema-general.ts", "schema"),
            ("posthog/schema_migrations/0001_foo.py", "schema"),
            ("posthog/api/serializers.py", "openapi"),
            ("posthog/api/dashboard/views.py", "openapi"),
            ("ee/api/some_view.py", "openapi"),
            ("products/surveys/backend/api/serializers.py", "openapi"),
            ("products/surveys/backend/presentation/views.py", "openapi"),
            ("products/surveys/mcp/tools.yaml", "openapi"),
            ("services/mcp/definitions/core.yaml", "openapi"),
            ("posthog/hogql/grammar/HogQLParser.g4", "grammar"),
            ("posthog/taxonomy/taxonomy.py", "taxonomy"),
            ("products/surveys/frontend/src/Survey.tsx", "products"),
            ("products/posthog_ai/skills/foo/SKILL.md", "skills"),
            ("services/mcp/src/handlers/foo.ts", "schema-mcp"),
        ],
    )
    def test_file_triggers_expected_pipeline(self, path: str, expected_pipeline: str) -> None:
        pipelines = _match_pipelines({path})
        names = [p.name for p in pipelines]
        assert expected_pipeline in names

    @pytest.mark.parametrize(
        "path",
        [
            "README.md",
            "posthog/models/team.py",
            "frontend/src/scenes/dashboard/Dashboard.tsx",
            ".github/workflows/ci.yml",
            "docker-compose.yml",
        ],
    )
    def test_unrelated_file_triggers_no_pipeline(self, path: str) -> None:
        pipelines = _match_pipelines({path})
        assert pipelines == []

    def test_multiple_files_trigger_multiple_pipelines(self) -> None:
        changed = {
            "frontend/src/queries/schema/index.ts",
            "posthog/api/serializers.py",
            "posthog/hogql/grammar/HogQLParser.g4",
        }
        pipelines = _match_pipelines(changed)
        names = {p.name for p in pipelines}
        assert names == {"schema", "openapi", "grammar"}

    def test_empty_changeset_triggers_nothing(self) -> None:
        assert _match_pipelines(set()) == []


class TestGetChangedFiles:
    @patch("hogli.build.subprocess.check_output")
    def test_combines_branch_staged_unstaged_untracked(self, mock_output: MagicMock) -> None:
        mock_output.side_effect = [
            "abc123\n",  # merge-base
            "file_branch.py\n",  # branch diff
            "file_staged.py\n",  # staged
            "file_unstaged.py\n",  # unstaged
            "file_untracked.py\n",  # untracked
        ]
        result = _get_changed_files()
        assert result == {"file_branch.py", "file_staged.py", "file_unstaged.py", "file_untracked.py"}

    @patch("hogli.build.subprocess.check_output")
    def test_deduplicates_files(self, mock_output: MagicMock) -> None:
        mock_output.side_effect = [
            "abc123\n",
            "same_file.py\n",
            "same_file.py\n",
            "same_file.py\n",
            "",
        ]
        result = _get_changed_files()
        assert result == {"same_file.py"}

    @patch("hogli.build.subprocess.check_output")
    def test_handles_all_git_failures_gracefully(self, mock_output: MagicMock) -> None:
        from subprocess import CalledProcessError

        mock_output.side_effect = CalledProcessError(1, "git")
        result = _get_changed_files()
        assert result == set()


class TestBuildCommand:
    def test_list_shows_all_pipelines(self) -> None:
        result = runner.invoke(cli, ["build", "--list"])
        assert result.exit_code == 0
        for p in PIPELINES:
            assert p.name in result.output
            assert p.command in result.output

    @patch("hogli.build._get_changed_files")
    def test_no_changes_exits_cleanly(self, mock_changed: MagicMock) -> None:
        mock_changed.return_value = set()
        result = runner.invoke(cli, ["build"])
        assert result.exit_code == 0
        assert "Nothing to rebuild" in result.output

    @patch("hogli.build._get_changed_files")
    def test_unrelated_changes_exits_cleanly(self, mock_changed: MagicMock) -> None:
        mock_changed.return_value = {"README.md", "docs/foo.md"}
        result = runner.invoke(cli, ["build"])
        assert result.exit_code == 0
        assert "don't match any build pipeline" in result.output

    @patch("hogli.build._run_pipeline")
    @patch("hogli.build._get_changed_files")
    def test_smart_mode_runs_matching_pipelines(self, mock_changed: MagicMock, mock_run: MagicMock) -> None:
        mock_changed.return_value = {"frontend/src/queries/schema/index.ts"}
        mock_run.return_value = True
        result = runner.invoke(cli, ["build"])
        assert result.exit_code == 0
        mock_run.assert_called_once()
        pipeline_arg = mock_run.call_args[0][0]
        assert pipeline_arg.name == "schema"

    @patch("hogli.build._run_pipeline")
    def test_force_runs_all_pipelines(self, mock_run: MagicMock) -> None:
        mock_run.return_value = True
        result = runner.invoke(cli, ["build", "--force"])
        assert result.exit_code == 0
        assert mock_run.call_count == len(PIPELINES)

    @patch("hogli.build._run_pipeline")
    @patch("hogli.build._get_changed_files")
    def test_dry_run_does_not_execute(self, mock_changed: MagicMock, mock_run: MagicMock) -> None:
        mock_changed.return_value = {"posthog/api/views.py"}
        result = runner.invoke(cli, ["build", "--dry-run"])
        assert result.exit_code == 0
        assert "openapi" in result.output
        mock_run.assert_not_called()

    @patch("hogli.build._run_pipeline")
    def test_force_dry_run_lists_all(self, mock_run: MagicMock) -> None:
        result = runner.invoke(cli, ["build", "--force", "--dry-run"])
        assert result.exit_code == 0
        for p in PIPELINES:
            assert p.name in result.output
        mock_run.assert_not_called()

    @patch("hogli.build._run_pipeline")
    def test_continues_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = [False, True, True, True, True, True, True]
        result = runner.invoke(cli, ["build", "--force"])
        assert result.exit_code == 1
        assert "failures" in result.output
        assert mock_run.call_count == len(PIPELINES)
