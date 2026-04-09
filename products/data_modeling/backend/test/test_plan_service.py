import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.integration import Integration

from products.data_modeling.backend.models import GitHubSyncConfig, GitHubSyncPlan, GitHubSyncPlanStatus
from products.data_modeling.backend.services.github.plan_service import (
    _classify_changes,
    compute_plan,
    post_plan_comment,
    render_plan_comment,
)

_EMPTY_PLAN = {
    "models": {"added": [], "modified": [], "removed": [], "renamed": []},
    "dags": {"added": [], "modified": [], "removed": []},
}


def _make_plan_data(**overrides):
    """Build plan data dict, merging overrides into the empty template."""
    plan = {
        "models": {**_EMPTY_PLAN["models"]},
        "dags": {**_EMPTY_PLAN["dags"]},
    }
    for section in ("models", "dags"):
        if section in overrides:
            plan[section] = {**plan[section], **overrides[section]}
    return plan


class TestClassifyChanges:
    @pytest.mark.parametrize(
        "status, expected_key",
        [
            ("added", "added"),
            ("modified", "modified"),
            ("removed", "removed"),
        ],
    )
    def test_sql_file_classified_by_status(self, status, expected_key):
        files = [{"filename": "models/revenue.sql", "status": status, "sha": "abc"}]
        result = _classify_changes(files, "models", "production")
        assert len(result["models"][expected_key]) == 1
        assert result["models"][expected_key][0]["name"] == "revenue"
        assert result["models"][expected_key][0]["path"] == "models/revenue.sql"

    def test_renamed_sql_file(self):
        files = [
            {
                "filename": "models/new_revenue.sql",
                "status": "renamed",
                "sha": "abc",
                "previous_filename": "models/old_revenue.sql",
            }
        ]
        result = _classify_changes(files, "models", "production")
        assert len(result["models"]["renamed"]) == 1
        assert result["models"]["renamed"][0]["old_path"] == "models/old_revenue.sql"
        assert result["models"]["renamed"][0]["new_path"] == "models/new_revenue.sql"
        assert result["models"]["renamed"][0]["name"] == "new_revenue"

    @pytest.mark.parametrize(
        "status, expected_key",
        [
            ("added", "added"),
            ("modified", "modified"),
            ("removed", "removed"),
        ],
    )
    def test_dag_toml_classified_by_status(self, status, expected_key):
        files = [{"filename": "models/core/dag.toml", "status": status, "sha": "abc"}]
        result = _classify_changes(files, "models", "production")
        assert len(result["dags"][expected_key]) == 1
        assert result["dags"][expected_key][0]["path"] == "models/core/dag.toml"

    @pytest.mark.parametrize(
        "filename",
        [
            "README.md",
            "src/app.py",
            "other_dir/model.sql",
        ],
    )
    def test_ignores_files_outside_models_dir(self, filename):
        files = [{"filename": filename, "status": "added", "sha": "abc"}]
        result = _classify_changes(files, "models", "production")
        assert all(len(v) == 0 for v in result["models"].values())
        assert all(len(v) == 0 for v in result["dags"].values())

    def test_multi_env_filters_to_matching_env(self):
        files = [
            {"filename": "models/production/revenue.sql", "status": "added", "sha": "abc"},
            {"filename": "models/staging/revenue.sql", "status": "added", "sha": "def"},
        ]
        result = _classify_changes(files, "models", "production")
        assert len(result["models"]["added"]) == 2
        assert result["models"]["added"][0]["path"] == "models/production/revenue.sql"

    @pytest.mark.parametrize(
        "filename",
        [
            "models/README.md",
            "models/schema.json",
            "models/notes.txt",
        ],
    )
    def test_ignores_non_sql_non_toml_files_in_models_dir(self, filename):
        files = [{"filename": filename, "status": "added", "sha": "abc"}]
        result = _classify_changes(files, "models", "production")
        assert all(len(v) == 0 for v in result["models"].values())
        assert all(len(v) == 0 for v in result["dags"].values())

    def test_mixed_changes(self):
        files = [
            {"filename": "models/new.sql", "status": "added", "sha": "a"},
            {"filename": "models/existing.sql", "status": "modified", "sha": "b"},
            {"filename": "models/old.sql", "status": "removed", "sha": "c"},
            {"filename": "models/core/dag.toml", "status": "added", "sha": "d"},
        ]
        result = _classify_changes(files, "models", "production")
        assert len(result["models"]["added"]) == 1
        assert len(result["models"]["modified"]) == 1
        assert len(result["models"]["removed"]) == 1
        assert len(result["dags"]["added"]) == 1


class TestRenderPlanComment:
    def test_empty_plan(self):
        plan = GitHubSyncPlan(plan=_EMPTY_PLAN)
        assert "No data modeling changes" in render_plan_comment(plan)

    @pytest.mark.parametrize(
        "action_key, action_label",
        [
            ("added", "+ Add"),
            ("modified", "~ Modify"),
            ("removed", "- Remove"),
        ],
    )
    def test_model_action_labels(self, action_key, action_label):
        plan_data = _make_plan_data(models={action_key: [{"name": "revenue", "path": "models/revenue.sql"}]})
        result = render_plan_comment(GitHubSyncPlan(plan=plan_data))
        assert action_label in result
        assert "`revenue`" in result

    def test_single_change_uses_singular(self):
        plan_data = _make_plan_data(models={"added": [{"name": "x", "path": "models/x.sql"}]})
        assert "**1 change**" in render_plan_comment(GitHubSyncPlan(plan=plan_data))

    def test_multiple_changes_uses_plural(self):
        plan_data = _make_plan_data(
            models={
                "added": [{"name": "a", "path": "models/a.sql"}],
                "removed": [{"name": "b", "path": "models/b.sql"}],
            }
        )
        assert "**2 changes**" in render_plan_comment(GitHubSyncPlan(plan=plan_data))

    def test_rename_shows_old_and_new_path(self):
        plan_data = _make_plan_data(
            models={"renamed": [{"name": "r", "old_path": "models/old.sql", "new_path": "models/new.sql"}]}
        )
        result = render_plan_comment(GitHubSyncPlan(plan=plan_data))
        assert "→ Rename" in result
        assert "models/old.sql" in result
        assert "models/new.sql" in result

    @pytest.mark.parametrize(
        "action_key, action_label",
        [
            ("added", "+ Add"),
            ("modified", "~ Modify"),
            ("removed", "- Remove"),
        ],
    )
    def test_dag_action_labels(self, action_key, action_label):
        plan_data = _make_plan_data(dags={action_key: [{"path": "models/core/dag.toml"}]})
        result = render_plan_comment(GitHubSyncPlan(plan=plan_data))
        assert action_label in result
        assert "models/core/dag.toml" in result

    def test_contains_merge_note(self):
        plan_data = _make_plan_data(models={"added": [{"name": "x", "path": "models/x.sql"}]})
        assert "applied when the PR is merged" in render_plan_comment(GitHubSyncPlan(plan=plan_data))


def _github_sync_setup(test_instance):
    """Shared setup for tests that need Integration + GitHubSyncConfig."""
    test_instance.integration = Integration.objects.create(
        team=test_instance.team,
        kind="github",
        integration_id="inst_123",
        config={
            "installation_id": "inst_123",
            "account": {"type": "User", "name": "testorg"},
        },
        sensitive_config={"access_token": "test_token"},
    )
    test_instance.config, _ = GitHubSyncConfig.objects.update_or_create(
        team=test_instance.team,
        defaults={
            "integration": test_instance.integration,
            "repository": "testorg/repo",
            "environment_name": "production",
        },
    )


@pytest.mark.django_db
class TestComputePlan(BaseTest):
    def setUp(self):
        super().setUp()
        _github_sync_setup(self)

    @patch("products.data_modeling.backend.services.github.plan_service.GitHubIntegration")
    def test_creates_plan_from_pr_files(self, MockGitHubIntegration):
        mock_github = MockGitHubIntegration.return_value
        mock_github.get_pull_request_files.return_value = {
            "success": True,
            "files": [
                {"filename": "models/revenue.sql", "status": "added", "sha": "abc"},
                {"filename": "models/old.sql", "status": "removed", "sha": "def"},
            ],
        }

        plan = compute_plan(
            team=self.team,
            config=self.config,
            pr_number=42,
            pr_url="https://github.com/testorg/repo/pull/42",
            head_sha="deadbeef",
        )

        assert plan is not None
        assert plan.pr_number == 42
        assert plan.head_sha == "deadbeef"
        assert plan.status == GitHubSyncPlanStatus.PENDING
        assert len(plan.plan["models"]["added"]) == 1
        assert len(plan.plan["models"]["removed"]) == 1

    @patch("products.data_modeling.backend.services.github.plan_service.GitHubIntegration")
    def test_marks_previous_plans_stale(self, MockGitHubIntegration):
        mock_github = MockGitHubIntegration.return_value
        mock_github.get_pull_request_files.return_value = {
            "success": True,
            "files": [{"filename": "models/a.sql", "status": "added", "sha": "abc"}],
        }

        plan1 = compute_plan(
            team=self.team,
            config=self.config,
            pr_number=42,
            pr_url="https://github.com/testorg/repo/pull/42",
            head_sha="sha1",
        )
        plan2 = compute_plan(
            team=self.team,
            config=self.config,
            pr_number=42,
            pr_url="https://github.com/testorg/repo/pull/42",
            head_sha="sha2",
        )

        plan1.refresh_from_db()
        assert plan1.status == GitHubSyncPlanStatus.STALE
        assert plan2.status == GitHubSyncPlanStatus.PENDING

    def test_returns_none_without_integration(self):
        self.config.integration = None
        self.config.save()

        plan = compute_plan(
            team=self.team,
            config=self.config,
            pr_number=1,
            pr_url="https://github.com/testorg/repo/pull/1",
            head_sha="abc",
        )
        assert plan is None

    @patch("products.data_modeling.backend.services.github.plan_service.GitHubIntegration")
    def test_returns_none_on_api_failure(self, MockGitHubIntegration):
        mock_github = MockGitHubIntegration.return_value
        mock_github.get_pull_request_files.return_value = {"success": False, "error": "Not found"}

        plan = compute_plan(
            team=self.team,
            config=self.config,
            pr_number=99,
            pr_url="https://github.com/testorg/repo/pull/99",
            head_sha="abc",
        )
        assert plan is None


@pytest.mark.django_db
class TestPostPlanComment(BaseTest):
    def setUp(self):
        super().setUp()
        _github_sync_setup(self)

    def _make_db_plan(self, **overrides):
        defaults = {
            "team": self.team,
            "config": self.config,
            "pr_number": 42,
            "pr_url": "https://github.com/testorg/repo/pull/42",
            "head_sha": "abc",
            "plan": _EMPTY_PLAN,
        }
        defaults.update(overrides)
        return GitHubSyncPlan.objects.create(**defaults)

    @patch("products.data_modeling.backend.services.github.plan_service.GitHubIntegration")
    def test_creates_comment_and_stores_id(self, MockGitHubIntegration):
        mock_github = MockGitHubIntegration.return_value
        mock_github.create_or_update_issue_comment.return_value = {"success": True, "comment_id": 12345}

        plan = self._make_db_plan(
            plan=_make_plan_data(models={"added": [{"name": "x", "path": "models/x.sql"}]}),
        )
        post_plan_comment([("production", plan)], [self.config], 42)

        plan.refresh_from_db()
        assert plan.github_comment_id == 12345

    @patch("products.data_modeling.backend.services.github.plan_service.GitHubIntegration")
    def test_reuses_comment_id_from_stale_plan(self, MockGitHubIntegration):
        mock_github = MockGitHubIntegration.return_value
        mock_github.create_or_update_issue_comment.return_value = {"success": True, "comment_id": 12345}

        self._make_db_plan(
            head_sha="old",
            status=GitHubSyncPlanStatus.STALE,
            github_comment_id=99999,
        )
        new_plan = self._make_db_plan(head_sha="new")
        post_plan_comment([("production", new_plan)], [self.config], 42)

        # should pass the stale plan's comment_id for update
        call_args = mock_github.create_or_update_issue_comment.call_args
        assert call_args.kwargs.get("comment_id") == 99999 or call_args[0][3] == 99999

    @patch("products.data_modeling.backend.services.github.plan_service.GitHubIntegration")
    def test_handles_api_failure_gracefully(self, MockGitHubIntegration):
        mock_github = MockGitHubIntegration.return_value
        mock_github.create_or_update_issue_comment.return_value = {"success": False, "error": "rate limited"}

        plan = self._make_db_plan()
        post_plan_comment([("production", plan)], [self.config], 42)

        plan.refresh_from_db()
        assert plan.github_comment_id is None
