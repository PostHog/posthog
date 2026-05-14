"""End-to-end tests for the public Deployments API.

Covers both top-level routes:
- /api/projects/{team_id}/deployment_projects/...
- /api/projects/{team_id}/deployment_projects/{pid}/deployments/...

The feature flag gate (`DeploymentsAccessPermission`) is mocked via
`posthoganalytics.feature_enabled` — see `products/deployments/backend/access.py`.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.integration import Integration
from posthog.models.utils import uuid7

from products.deployments.backend.adapters.github import GitHubBranch, GitHubRepository
from products.deployments.backend.models import Deployment, DeploymentProject
from products.deployments.backend.test._helpers import DeploymentsTeamScopedTestMixin

from ee.models.rbac.access_control import AccessControl


class _BaseDeploymentsAPITest(DeploymentsTeamScopedTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Force the feature flag on for every test in this module — it's
        # the same gate the scaffold's test_list_respects_feature_flag
        # covered separately.
        self._flag_patcher = patch(
            "products.deployments.backend.access.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self._flag_patcher.start()
        self.addCleanup(self._flag_patcher.stop)


class TestDeploymentProjectsAPI(_BaseDeploymentsAPITest):
    def _enable_advanced_permissions(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS}
        ]
        self.organization.save(update_fields=["available_product_features"])

    def _restrict_integrations_resource(self) -> None:
        self._enable_advanced_permissions()
        AccessControl.objects.create(
            team=self.team,
            resource="integration",
            resource_id=None,
            access_level="none",
        )

    def _restrict_integration(self, integration: Integration) -> None:
        self._enable_advanced_permissions()
        AccessControl.objects.create(
            team=self.team,
            resource="integration",
            resource_id=str(integration.id),
            access_level="none",
        )

    def _github_integration(self) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.GITHUB.value,
            integration_id="12345",
            config={"account": {"name": "PostHog", "type": "Organization"}},
            sensitive_config={"access_token": "ghs_test"},
            errors="",
        )

    def test_list_returns_empty_when_no_projects(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/deployment_projects/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    def test_list_excludes_soft_deleted(self) -> None:
        DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Alive",
            slug="alive",
            repo_url="https://github.com/example-org/alive",
        )
        DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Dead",
            slug="dead",
            repo_url="https://github.com/example-org/dead",
            deleted=True,
            deleted_at=timezone.now(),
        )
        response = self.client.get(f"/api/projects/{self.team.id}/deployment_projects/")
        results = response.json()["results"]
        slugs = [p["slug"] for p in results]
        self.assertEqual(slugs, ["alive"])

    def test_create_project_rejects_repo_url_input(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/deployment_projects/",
            {
                "name": "Site",
                "slug": "site",
                "repo_url": "https://github.com/example-org/site",
                "github_integration_id": 42,
                "github_repo_id": 42,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(response.json().get("attr"), "repo_url")

    def test_github_integration_must_belong_to_team(self) -> None:
        # An integration from another team is not selectable.
        other_team = self.organization.teams.create(name="Other")
        outsider = Integration.objects.create(
            team=other_team,
            kind="github",
            integration_id="99",
            sensitive_config={"access_token": "ghs_other"},
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/deployment_projects/",
            {
                "name": "Site",
                "slug": "site",
                "github_integration_id": outsider.id,
                "github_repo_id": 42,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.content)

    def test_github_integration_kind_must_be_github(self) -> None:
        slack = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            sensitive_config={"access_token": "xoxb-not-github"},
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/deployment_projects/",
            {
                "name": "Site",
                "slug": "site",
                "github_integration_id": slack.id,
                "github_repo_id": 42,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.content)

    @patch("products.deployments.backend.api.deployment_projects.get_github_adapter")
    def test_create_provisions_cloudflare_via_null_adapter(self, mock_get_github_adapter: MagicMock) -> None:
        integration = self._github_integration()
        adapter = mock_get_github_adapter.return_value
        adapter.get_repository_by_id.return_value = GitHubRepository(
            id=42,
            full_name="example-org/site",
            default_branch="main",
            html_url="https://github.com/example-org/site",
        )
        adapter.get_branch.return_value = GitHubBranch(name="main", sha="abc123")

        response = self.client.post(
            f"/api/projects/{self.team.id}/deployment_projects/",
            {
                "name": "Site",
                "slug": "site",
                "github_integration_id": integration.id,
                "github_repo_id": 42,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        body = response.json()
        # Null adapter assigns a {team_id}-{slug} name; serializer surfaces
        # the cloudflare_project_name as a read-only field. The subdomain
        # mirrors whatever the adapter returned (Null = `{name}.pages.dev`)
        # — provisioning persists the adapter's value rather than a
        # hardcoded pattern so two teams with the same slug don't collide.
        self.assertIn(f"{self.team.id}-site", body["cloudflare_project_name"])
        self.assertEqual(body["subdomain"], f"{self.team.id}-site.pages.dev")
        self.assertIsNotNone(body["cloudflare_ready_at"])

    @patch("products.deployments.backend.api.deployment_projects.get_github_adapter")
    def test_create_project_uses_existing_github_integration(self, mock_get_github_adapter: MagicMock) -> None:
        integration = self._github_integration()
        adapter = mock_get_github_adapter.return_value
        adapter.get_repository_by_id.return_value = GitHubRepository(
            id=42,
            full_name="PostHog/posthog",
            default_branch="master",
            html_url="https://github.com/PostHog/posthog",
        )
        adapter.get_branch.return_value = GitHubBranch(name="master", sha="abc123")

        response = self.client.post(
            f"/api/projects/{self.team.id}/deployment_projects/",
            {
                "name": "Site",
                "slug": "site",
                "github_integration_id": integration.id,
                "github_repo_id": 42,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        body = response.json()
        self.assertEqual(body["github_integration_id"], integration.id)
        self.assertEqual(body["github_repo_id"], 42)
        self.assertEqual(body["repo_url"], "https://github.com/PostHog/posthog")
        self.assertEqual(body["default_branch"], "master")
        project = DeploymentProject.all_teams.get(team_id=self.team.id, github_repo_id=42)
        self.assertEqual(project.github_integration_id, integration.id)

    @patch("products.deployments.backend.api.deployment_projects.get_github_adapter")
    def test_update_project_rejects_repo_url_input(self, mock_get_github_adapter: MagicMock) -> None:
        integration = self._github_integration()
        project = DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Site",
            slug="site",
            repo_url="https://github.com/PostHog/posthog",
            github_integration_id=integration.id,
            github_repo_id=42,
            default_branch="master",
        )

        response = self.client.put(
            f"/api/projects/{self.team.id}/deployment_projects/{project.id}/",
            {
                "name": "Renamed site",
                "slug": "site",
                "repo_url": "https://github.com/Other/repo",
                "github_integration_id": integration.id,
                "github_repo_id": 42,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual(response.json().get("attr"), "repo_url")
        mock_get_github_adapter.assert_not_called()
        project.refresh_from_db()
        self.assertEqual(project.repo_url, "https://github.com/PostHog/posthog")

    @parameterized.expand(
        [
            ("resource",),
            ("object",),
        ]
    )
    @patch("products.deployments.backend.api.deployment_projects.get_github_adapter")
    def test_create_project_rejects_restricted_github_integration(
        self, restriction_kind: str, mock_get_github_adapter: MagicMock
    ) -> None:
        integration = self._github_integration()
        if restriction_kind == "resource":
            self._restrict_integrations_resource()
        else:
            self._restrict_integration(integration)

        response = self.client.post(
            f"/api/projects/{self.team.id}/deployment_projects/",
            {
                "name": "Site",
                "slug": "site",
                "github_integration_id": integration.id,
                "github_repo_id": 42,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_get_github_adapter.return_value.get_repository_by_id.assert_not_called()

    def test_create_project_rejects_non_project_github_integration(self) -> None:
        other_team = self.organization.teams.create(name="Other team")
        integration = Integration.objects.create(
            team=other_team,
            kind=Integration.IntegrationKind.GITHUB.value,
            integration_id="12345",
            config={},
            sensitive_config={"access_token": "ghs_test"},
            errors="",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/deployment_projects/",
            {
                "name": "Site",
                "slug": "site",
                "github_integration_id": integration.id,
                "github_repo_id": 42,
                "default_branch": "master",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("products.deployments.backend.api.deployment_projects.get_github_adapter")
    def test_refresh_project_returns_current_branch_sha(self, mock_get_github_adapter: MagicMock) -> None:
        integration = self._github_integration()
        project = DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Site",
            slug="site",
            repo_url="https://github.com/PostHog/posthog",
            github_integration_id=integration.id,
            github_repo_id=42,
            default_branch="master",
        )
        adapter = mock_get_github_adapter.return_value
        adapter.get_repository_by_id.return_value = GitHubRepository(
            id=42,
            full_name="PostHog/posthog",
            default_branch="main",
            html_url="https://github.com/PostHog/posthog",
        )
        adapter.get_branch.return_value = GitHubBranch(name="master", sha="new-sha")

        response = self.client.post(f"/api/projects/{self.team.id}/deployment_projects/{project.id}/refresh/")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertEqual(body["default_branch"], "master")
        self.assertEqual(body["commit_sha"], "new-sha")
        project.refresh_from_db()
        self.assertEqual(project.default_branch, "master")

    @patch("products.deployments.backend.api.deployment_projects.get_github_adapter")
    def test_refresh_project_rejects_restricted_github_integration(self, mock_get_github_adapter: MagicMock) -> None:
        integration = self._github_integration()
        self._restrict_integration(integration)
        project = DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Site",
            slug="site",
            repo_url="https://github.com/PostHog/posthog",
            github_integration_id=integration.id,
            github_repo_id=42,
            default_branch="master",
        )

        response = self.client.post(f"/api/projects/{self.team.id}/deployment_projects/{project.id}/refresh/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_get_github_adapter.return_value.get_repository_by_id.assert_not_called()

    def test_destroy_is_soft_delete(self) -> None:
        project = DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Site",
            slug="site",
            repo_url="https://github.com/example-org/site",
        )
        response = self.client.delete(f"/api/projects/{self.team.id}/deployment_projects/{project.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        # Row still exists but flagged deleted.
        project.refresh_from_db()
        self.assertTrue(project.deleted)
        self.assertIsNotNone(project.deleted_at)


class TestDeploymentsAPINested(_BaseDeploymentsAPITest):
    def setUp(self) -> None:
        super().setUp()
        self.deployment_project = DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Site",
            slug="site",
            repo_url="https://github.com/example-org/site",
            cloudflare_project_name=f"{self.team.id}-site",
            subdomain="site.posthog-app.com",
            cloudflare_ready_at=timezone.now(),
        )

    def test_list_returns_empty_when_no_deployments(self) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/deployment_projects/{self.deployment_project.id}/deployments/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    def test_unknown_project_returns_404(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/deployment_projects/{uuid7()}/deployments/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_post_creates_deployment(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/deployment_projects/{self.deployment_project.id}/deployments/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        body = response.json()
        self.assertEqual(body["status"], Deployment.Status.QUEUED.value)
        self.assertEqual(body["trigger_kind"], Deployment.TriggerKind.MANUAL.value)

    def test_second_concurrent_post_returns_409(self) -> None:
        # First create: succeeds.
        first = self.client.post(
            f"/api/projects/{self.team.id}/deployment_projects/{self.deployment_project.id}/deployments/",
            {},
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.content)
        # Second: the partial unique constraint fires.
        second = self.client.post(
            f"/api/projects/{self.team.id}/deployment_projects/{self.deployment_project.id}/deployments/",
            {},
            format="json",
        )
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT, second.content)
        body = second.json()
        self.assertEqual(body["active_deployment_id"], first.json()["id"])

    def test_list_default_filter_hides_cancelled(self) -> None:
        ready = Deployment.objects.create(
            project=self.deployment_project,
            team_id=self.team.id,
            status=Deployment.Status.READY.value,
        )
        Deployment.objects.create(
            project=self.deployment_project,
            team_id=self.team.id,
            status=Deployment.Status.CANCELLED.value,
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/deployment_projects/{self.deployment_project.id}/deployments/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [d["id"] for d in response.json()["results"]]
        self.assertEqual(ids, [str(ready.id)])

    def test_list_with_explicit_status_filter_reveals_cancelled(self) -> None:
        cancelled = Deployment.objects.create(
            project=self.deployment_project,
            team_id=self.team.id,
            status=Deployment.Status.CANCELLED.value,
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/deployment_projects/{self.deployment_project.id}/deployments/?status=cancelled"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [d["id"] for d in response.json()["results"]]
        self.assertEqual(ids, [str(cancelled.id)])

    def test_is_current_annotated_against_project_pointer(self) -> None:
        deployment = Deployment.objects.create(
            project=self.deployment_project,
            team_id=self.team.id,
            status=Deployment.Status.READY.value,
        )
        self.deployment_project.current_deployment = deployment
        self.deployment_project.save(update_fields=["current_deployment"])

        response = self.client.get(
            f"/api/projects/{self.team.id}/deployment_projects/{self.deployment_project.id}/deployments/"
        )
        body = response.json()["results"][0]
        self.assertTrue(body["is_current"])

    def test_action_endpoint_refuses_cross_project_deployment_id(self) -> None:
        # Regression for the cross-project IDOR on action endpoints: a
        # deployment belonging to project B must not be reachable via
        # project A's URL, even within the same team.
        other_project = DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Other",
            slug="other",
            repo_url="https://github.com/example-org/other",
        )
        other_deployment = Deployment.objects.create(
            project=other_project,
            team_id=self.team.id,
            status=Deployment.Status.READY.value,
            commit_sha="abc1234",
        )
        # Hit the WRONG project's URL with the right deployment id.
        response = self.client.post(
            f"/api/projects/{self.team.id}/deployment_projects/{self.deployment_project.id}/deployments/{other_deployment.id}/redeploy/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.content)

    def test_redeploy_of_cancelled_deployment_succeeds(self) -> None:
        # Detail / action lookups must NOT inherit the list-only filters
        # (status / author / hide-cancelled). Redeploying a cancelled row
        # is a valid operation and the URL clearly references it.
        cancelled = Deployment.objects.create(
            project=self.deployment_project,
            team_id=self.team.id,
            status=Deployment.Status.CANCELLED.value,
            commit_sha="abc1234",
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/deployment_projects/{self.deployment_project.id}/deployments/{cancelled.id}/redeploy/"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)


class TestDeploymentsFeatureFlag(_BaseDeploymentsAPITest):
    """Re-verifies the feature-flag gate over the new nested URL."""

    @patch("products.deployments.backend.api.deployment_projects.get_github_adapter")
    def test_create_feature_flag_off_does_not_call_github(self, mock_get_github_adapter: MagicMock) -> None:
        self._flag_patcher.stop()
        with patch(
            "products.deployments.backend.access.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/deployment_projects/",
                {
                    "name": "Site",
                    "slug": "site",
                    "github_integration_id": 42,
                    "github_repo_id": 42,
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_get_github_adapter.assert_not_called()
        self._flag_patcher.start()

    @parameterized.expand(
        [
            ("flag on returns empty list", True, status.HTTP_200_OK),
            ("flag off returns 403", False, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_list_respects_feature_flag(self, _name: str, flag_enabled: bool, expected_status: int) -> None:
        # Stop the module-wide patcher so this test can swap in its own
        # return value.
        self._flag_patcher.stop()
        with patch(
            "products.deployments.backend.access.posthoganalytics.feature_enabled",
            return_value=flag_enabled,
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/deployment_projects/")

        self.assertEqual(response.status_code, expected_status)
        if expected_status == status.HTTP_200_OK:
            self.assertEqual(response.json()["results"], [])
        # Re-start the cleanup-registered patcher so addCleanup's stop() is
        # safe (re-stop is fine since `stop` is idempotent on already-stopped).
        self._flag_patcher.start()
