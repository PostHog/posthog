from __future__ import annotations

from typing import cast

from unittest import TestCase
from unittest.mock import MagicMock, patch

from posthog.models.integration import Integration

from products.deployments.backend.adapters.github import (
    DEPLOYMENTS_GITHUB_API_TIMEOUT_SECONDS,
    GitHubIntegrationAdapter,
)


class TestGitHubIntegrationAdapter(TestCase):
    @patch("products.deployments.backend.adapters.github.GitHubIntegration._gh_api_get")
    def test_get_json_uses_short_request_path_timeout(self, mock_gh_api_get: MagicMock) -> None:
        mock_gh_api_get.return_value = {"ok": True}
        adapter = GitHubIntegrationAdapter()
        integration_mock = MagicMock()
        integration_mock.kind = "github"
        integration = cast(Integration, integration_mock)

        payload = adapter._get_json(
            integration=integration,
            path="/repositories/42",
            endpoint="/repositories/{repository_id}",
        )

        self.assertEqual(payload, {"ok": True})
        mock_gh_api_get.assert_called_once_with(
            "/repositories/42",
            endpoint="/repositories/{repository_id}",
            timeout=DEPLOYMENTS_GITHUB_API_TIMEOUT_SECONDS,
        )

    def test_get_repository_by_id_resolves_current_repository_by_numeric_id(self) -> None:
        adapter = GitHubIntegrationAdapter()
        integration = cast(Integration, MagicMock())

        with patch.object(
            adapter,
            "_get_json",
            return_value={
                "id": 42,
                "full_name": "PostHog/renamed-repo",
                "default_branch": "master",
                "html_url": "https://github.com/PostHog/renamed-repo",
            },
        ) as get_json:
            repository = adapter.get_repository_by_id(integration=integration, github_repo_id=42)

        get_json.assert_called_once_with(
            integration=integration,
            path="/repositories/42",
            endpoint="/repositories/{repository_id}",
        )
        self.assertEqual(repository.id, 42)
        self.assertEqual(repository.full_name, "PostHog/renamed-repo")
        self.assertEqual(repository.default_branch, "master")
        self.assertEqual(repository.html_url, "https://github.com/PostHog/renamed-repo")
