"""End-to-end tests for the public Deployments API.

Covers both top-level routes:
- /api/projects/{team_id}/deployment_projects/...
- /api/projects/{team_id}/deployment_projects/{pid}/deployments/...

The feature flag gate (`DeploymentsAccessPermission`) is mocked via
`posthoganalytics.feature_enabled` — see `products/deployments/backend/access.py`.
"""

from __future__ import annotations

import uuid as uuidlib
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.models.event.util import bulk_create_events
from posthog.models.integration import Integration
from posthog.models.utils import uuid7

from products.deployments.backend.adapters.github import GitHubBranch, GitHubRepository
from products.deployments.backend.api.deployments import LOGS_ROW_LIMIT
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
    def _enable_access_control(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])

    def _restrict_integrations_resource(self) -> None:
        self._enable_access_control()
        AccessControl.objects.create(
            team=self.team,
            resource="integration",
            resource_id=None,
            access_level="none",
        )

    def _restrict_integration(self, integration: Integration) -> None:
        self._enable_access_control()
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


class TestDeploymentLogsEndpoint(
    ClickhouseTestMixin,
    DeploymentsTeamScopedTestMixin,
    APIBaseTest,
):
    """GET /deployments/{id}/logs/ — HogQL proxy over `$log` events."""

    def setUp(self) -> None:
        super().setUp()
        # The feature-flag gate is patched on for the whole suite below;
        # `_BaseDeploymentsAPITest` already does this elsewhere but this
        # class inherits `APIBaseTest` directly (we need ClickhouseTestMixin
        # in front of APIBaseTest, which doesn't compose with the existing
        # `_BaseDeploymentsAPITest` cleanly).
        self._flag_patcher = patch(
            "products.deployments.backend.access.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self._flag_patcher.start()
        self.addCleanup(self._flag_patcher.stop)

        # Isolation: scrub the ClickHouse events table so rows from other
        # tests in the same session can't leak in. Mirrors the live_debugger
        # tests at products/live_debugger/backend/test_models.py:18.
        sync_execute("TRUNCATE TABLE IF EXISTS sharded_events")

        self.deployment_project = DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Site",
            slug="site",
            repo_url="https://github.com/example-org/site",
            cloudflare_project_name=f"{self.team.id}-site",
            subdomain="site.posthog-app.com",
            cloudflare_ready_at=timezone.now(),
        )
        self.deployment = Deployment.objects.create(
            project=self.deployment_project,
            team_id=self.team.id,
            status=Deployment.Status.READY.value,
            commit_sha="abc1234",
        )

    # ---- helpers ------------------------------------------------------

    def _logs_url(self, deployment_id: str | None = None, project_id: str | None = None) -> str:
        pid = project_id or str(self.deployment_project.id)
        did = deployment_id or str(self.deployment.id)
        return f"/api/projects/{self.team.id}/deployment_projects/{pid}/deployments/{did}/logs/"

    def _capture_log_event(
        self,
        *,
        deployment_id: str,
        level: str = "info",
        step: str = "build",
        line: str = "hello",
        exit_code: int | None = None,
        timestamp: dt.datetime | None = None,
        team_id: int | None = None,
        event: str = "$log",
    ) -> None:
        properties: dict[str, object] = {
            "deployment_id": deployment_id,
            "level": level,
            "step": step,
            "$log_line": line,
        }
        if exit_code is not None:
            properties["exit_code"] = exit_code
        bulk_create_events(
            [
                {
                    "uuid": str(uuidlib.uuid4()),
                    "event": event,
                    "team_id": team_id if team_id is not None else self.team.pk,
                    "distinct_id": "build-worker",
                    "timestamp": timestamp or dt.datetime.now(),  # nosemgrep: test-datetime-now-without-freeze
                    "properties": properties,
                }
            ]
        )

    # ---- tests --------------------------------------------------------

    def test_feature_flag_off_returns_403(self) -> None:
        self._flag_patcher.stop()
        with patch(
            "products.deployments.backend.access.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            response = self.client.get(self._logs_url())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.content)
        self._flag_patcher.start()

    def test_unknown_deployment_returns_404(self) -> None:
        response = self.client.get(self._logs_url(deployment_id=str(uuid7())))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_deployment_from_other_team_is_404(self) -> None:
        # Mirrors test_action_endpoint_refuses_cross_project_deployment_id —
        # we use get_object() so cross-team access surfaces as a clean 404,
        # not a leak.
        other_team = self.organization.teams.create(name="Other Team")
        other_project = DeploymentProject.objects.create(
            team_id=other_team.id,
            name="Other",
            slug="other",
            repo_url="https://github.com/example-org/other",
        )
        other_deployment = Deployment.objects.create(
            project=other_project,
            team_id=other_team.id,
            status=Deployment.Status.READY.value,
        )
        response = self.client.get(self._logs_url(deployment_id=str(other_deployment.id)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_deployment_from_sibling_project_is_404(self) -> None:
        sibling = DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Sibling",
            slug="sibling",
            repo_url="https://github.com/example-org/sibling",
        )
        sibling_deployment = Deployment.objects.create(
            project=sibling,
            team_id=self.team.id,
            status=Deployment.Status.READY.value,
        )
        # URL uses self.deployment_project, body references sibling's deployment.
        response = self.client.get(self._logs_url(deployment_id=str(sibling_deployment.id)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_empty_events_returns_empty_results(self) -> None:
        response = self.client.get(self._logs_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertEqual(body["results"], [])
        self.assertFalse(body["has_more"])
        self.assertEqual(body["row_limit"], LOGS_ROW_LIMIT)

    def test_returns_log_lines_in_ascending_order(self) -> None:
        deployment_id = str(self.deployment.id)
        base = dt.datetime(2026, 5, 14, 10, 0, 0)
        # Insert out of order so the test confirms server-side sort, not insertion order.
        self._capture_log_event(
            deployment_id=deployment_id,
            step="build",
            line="line-three",
            timestamp=base + dt.timedelta(seconds=2),
        )
        self._capture_log_event(
            deployment_id=deployment_id,
            step="install",
            line="line-one",
            timestamp=base,
        )
        self._capture_log_event(
            deployment_id=deployment_id,
            step="install",
            line="line-two",
            timestamp=base + dt.timedelta(seconds=1),
            exit_code=0,
        )

        response = self.client.get(self._logs_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        lines = [entry["line"] for entry in body["results"]]
        self.assertEqual(lines, ["line-one", "line-two", "line-three"])
        # exit_code projects through; non-final lines stay null.
        self.assertEqual(body["results"][0]["exit_code"], None)
        self.assertEqual(body["results"][1]["exit_code"], 0)
        self.assertEqual(body["results"][2]["exit_code"], None)
        # Each entry carries level and step from the event properties.
        self.assertEqual(body["results"][0]["level"], "info")
        self.assertEqual(body["results"][0]["step"], "install")
        self.assertFalse(body["has_more"])

    def test_excludes_logs_from_other_deployments_in_same_project(self) -> None:
        # The single guarantee that matters: filtering by
        # properties.deployment_id only returns this deployment's lines.
        other_deployment = Deployment.objects.create(
            project=self.deployment_project,
            team_id=self.team.id,
            status=Deployment.Status.READY.value,
        )
        self._capture_log_event(deployment_id=str(self.deployment.id), line="mine")
        self._capture_log_event(deployment_id=str(other_deployment.id), line="theirs")

        response = self.client.get(self._logs_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        lines = [entry["line"] for entry in response.json()["results"]]
        self.assertEqual(lines, ["mine"])

    def test_excludes_non_log_events_with_matching_deployment_id(self) -> None:
        # A non-`$log` event (e.g. a `$deployment` event or a customer's
        # own event) tagged with the same deployment_id must not leak in.
        deployment_id = str(self.deployment.id)
        self._capture_log_event(deployment_id=deployment_id, line="real-log")
        self._capture_log_event(
            deployment_id=deployment_id,
            line="should-not-show",
            event="$deployment",
        )

        response = self.client.get(self._logs_url())
        lines = [entry["line"] for entry in response.json()["results"]]
        self.assertEqual(lines, ["real-log"])

    def test_row_limit_signals_has_more_only_when_extra_row_exists(self) -> None:
        # We fetch LIMIT + 1 rows under the hood so `has_more` can
        # distinguish "ran out at exactly the cap" from "page is full and
        # more exist beyond it". Verify both paths and confirm the
        # placeholder values are bound by `ast.Constant`, not interpolated.
        deployment_id = str(self.deployment.id)

        def _synthetic(rows: int) -> list[tuple[dt.datetime, str, str, str, None]]:
            return [
                (dt.datetime(2026, 5, 14, 10, 0, 0, i % 1_000_000), "info", "build", f"line-{i}", None)
                for i in range(rows)
            ]

        # Exactly LOGS_ROW_LIMIT rows returned (no overflow row from DB) → has_more False.
        with patch("products.deployments.backend.api.deployments.execute_hogql_query") as mock_execute:
            mock_execute.return_value = MagicMock(results=_synthetic(LOGS_ROW_LIMIT))
            response = self.client.get(self._logs_url(deployment_id=deployment_id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertEqual(len(body["results"]), LOGS_ROW_LIMIT)
        self.assertFalse(body["has_more"])

        # LOGS_ROW_LIMIT + 1 rows returned (DB hit the overflow row) →
        # has_more True; response slices off the overflow.
        with patch("products.deployments.backend.api.deployments.execute_hogql_query") as mock_execute:
            mock_execute.return_value = MagicMock(results=_synthetic(LOGS_ROW_LIMIT + 1))
            response = self.client.get(self._logs_url(deployment_id=deployment_id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertEqual(len(body["results"]), LOGS_ROW_LIMIT)
        self.assertTrue(body["has_more"])

        # Confirm parameterization on the last call.
        placeholders = mock_execute.call_args.kwargs["placeholders"]
        self.assertEqual(placeholders["deployment_id"].value, deployment_id)
        self.assertEqual(placeholders["log_event"].value, "$log")
        # SQL fetches one extra row to support honest has_more.
        self.assertEqual(placeholders["row_limit"].value, LOGS_ROW_LIMIT + 1)
        # Response still advertises the user-facing cap, not the +1 internal.
        self.assertEqual(body["row_limit"], LOGS_ROW_LIMIT)

    def test_hogql_failure_returns_502(self) -> None:
        with patch(
            "products.deployments.backend.api.deployments.execute_hogql_query",
            side_effect=RuntimeError("ClickHouse offline"),
        ):
            response = self.client.get(self._logs_url())
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY, response.content)
        self.assertIn("detail", response.json())
