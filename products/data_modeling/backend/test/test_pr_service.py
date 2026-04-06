import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.integration import Integration

from products.data_modeling.backend.models import GitHubSyncConfig, GitHubSyncedModel
from products.data_modeling.backend.services.github.pr_service import create_pr_from_saved_query
from products.data_warehouse.backend.models import DataWarehouseSavedQuery


@pytest.mark.django_db
class TestCreatePrFromSavedQuery(BaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="inst_123",
            config={
                "installation_id": "inst_123",
                "account": {"type": "User", "name": "testorg"},
            },
            sensitive_config={"access_token": "test_token"},
        )
        self.config, _ = GitHubSyncConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "integration": self.integration,
                "repository": "testorg/repo",
                "environment_name": "production",
            },
        )
        self.saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="revenue",
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        self.synced_model = GitHubSyncedModel.objects.create(
            team=self.team,
            saved_query=self.saved_query,
            file_path="models/revenue.sql",
            file_sha="original_sha",
            last_synced_sha="commit_abc",
        )

    @patch("products.data_modeling.backend.services.github.pr_service.GitHubIntegration")
    def test_creates_branch_commits_and_opens_pr(self, MockGitHubIntegration):
        mock_github = MockGitHubIntegration.return_value
        mock_github.create_branch.return_value = {
            "success": True,
            "branch_name": "posthog/update-revenue-abc",
            "sha": "base_sha",
        }
        mock_github.update_file.return_value = {
            "success": True,
            "commit_sha": "new_sha",
            "file_sha": "new_file_sha",
            "html_url": "...",
        }
        mock_github.create_pull_request.return_value = {
            "success": True,
            "pr_number": 99,
            "pr_url": "https://github.com/testorg/repo/pull/99",
            "pr_id": 1,
        }

        result = create_pr_from_saved_query(self.saved_query, query_text="SELECT 1")

        assert result["success"] is True
        assert result["pr_number"] == 99
        assert result["pr_url"] == "https://github.com/testorg/repo/pull/99"
        mock_github.create_branch.assert_called_once()
        mock_github.update_file.assert_called_once()
        mock_github.create_pull_request.assert_called_once()

    @patch("products.data_modeling.backend.services.github.pr_service.GitHubIntegration")
    def test_uses_correct_file_path_and_sha(self, MockGitHubIntegration):
        mock_github = MockGitHubIntegration.return_value
        mock_github.create_branch.return_value = {"success": True, "branch_name": "b", "sha": "s"}
        mock_github.update_file.return_value = {"success": True, "commit_sha": "c", "file_sha": "f", "html_url": "u"}
        mock_github.create_pull_request.return_value = {"success": True, "pr_number": 1, "pr_url": "u", "pr_id": 1}

        create_pr_from_saved_query(self.saved_query, query_text="SELECT 1")

        update_call = mock_github.update_file.call_args
        assert update_call[0][1] == "models/revenue.sql"  # file_path
        assert update_call.kwargs.get("sha") == "original_sha" or update_call[0][5] == "original_sha"

    def test_fails_for_non_synced_model(self):
        unsynced = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="local_only",
            query={"query": "SELECT 2", "kind": "HogQLQuery"},
        )

        result = create_pr_from_saved_query(unsynced, query_text="SELECT 2")

        assert result["success"] is False
        assert "not synced" in result["error"]

    def test_fails_without_github_config(self):
        GitHubSyncConfig.objects.filter(team=self.team).delete()

        result = create_pr_from_saved_query(self.saved_query, query_text="SELECT 1")

        assert result["success"] is False

    def test_fails_gracefully_at_each_step(self):
        cases = [
            (
                "create_branch",
                {"create_branch.return_value": {"success": False, "error": "branch exists"}},
            ),
            (
                "update_file",
                {
                    "create_branch.return_value": {"success": True, "branch_name": "b", "sha": "s"},
                    "update_file.return_value": {"success": False, "error": "conflict"},
                },
            ),
            (
                "create_pull_request",
                {
                    "create_branch.return_value": {"success": True, "branch_name": "b", "sha": "s"},
                    "update_file.return_value": {"success": True, "commit_sha": "c", "file_sha": "f", "html_url": "u"},
                    "create_pull_request.return_value": {"success": False, "error": "validation failed"},
                },
            ),
        ]
        for failing_step, mock_overrides in cases:
            with (
                self.subTest(failing_step=failing_step),
                patch(
                    "products.data_modeling.backend.services.github.pr_service.GitHubIntegration"
                ) as MockGitHubIntegration,
            ):
                mock_github = MockGitHubIntegration.return_value
                for attr, value in mock_overrides.items():
                    parts = attr.split(".")
                    obj = mock_github
                    for part in parts[:-1]:
                        obj = getattr(obj, part)
                    setattr(obj, parts[-1], value)

                result = create_pr_from_saved_query(self.saved_query, query_text="SELECT 1")

                assert result["success"] is False
                assert "error" in result
