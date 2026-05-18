"""End-to-end tests for the internal `/api/internal/deployments/*` endpoints.

These exercise the URL → InternalAPIAuthentication →
InternalDeploymentTransitionsViewSet → service path. Auth is verified
both negative (missing/wrong header) and positive (correct secret).
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest

from django.http import HttpResponse
from django.test import override_settings
from django.utils import timezone

from rest_framework import status as drf_status

from posthog.models.scoping import reset_current_team_id, set_current_team_id

from products.deployments.backend.domain.status import Status
from products.deployments.backend.models import Deployment, DeploymentEvent, DeploymentProject
from products.deployments.backend.test._helpers import DeploymentsTeamScopedTestMixin

SECRET = "test-internal-secret-abc123"


@override_settings(INTERNAL_API_SECRET=SECRET)
class TestInternalDeploymentTransitions(DeploymentsTeamScopedTestMixin, APIBaseTest):
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
        self.deployment = Deployment.objects.create(
            project=self.deployment_project,
            team_id=self.team.id,
            status=Deployment.Status.QUEUED.value,
            commit_sha="abc1234",
        )

    def _post_transition(self, body: dict, *, secret: str | None = SECRET) -> HttpResponse:
        headers: dict = {}
        if secret is not None:
            headers["x-internal-api-secret"] = secret
        return self.client.post(
            f"/api/internal/deployments/{self.deployment.id}/transitions/",
            body,
            format="json",
            headers=headers,
        )

    def test_valid_secret_walks_state_machine(self) -> None:
        response = self._post_transition({"status": Status.INITIALIZING.value})
        self.assertEqual(response.status_code, drf_status.HTTP_200_OK)
        self.deployment.refresh_from_db()
        self.assertEqual(self.deployment.status, Deployment.Status.INITIALIZING.value)
        self.assertIsNotNone(self.deployment.started_at)

    def test_valid_secret_runs_without_outer_team_scope(self) -> None:
        token = set_current_team_id(None)
        try:
            response = self._post_transition({"status": Status.INITIALIZING.value})
        finally:
            reset_current_team_id(token)

        self.assertEqual(response.status_code, drf_status.HTTP_200_OK, response.content)
        self.deployment.refresh_from_db()
        self.assertEqual(self.deployment.status, Deployment.Status.INITIALIZING.value)

    def test_missing_secret_returns_401(self) -> None:
        response = self._post_transition({"status": Status.INITIALIZING.value}, secret=None)
        self.assertEqual(response.status_code, drf_status.HTTP_401_UNAUTHORIZED)

    def test_wrong_secret_returns_401(self) -> None:
        response = self._post_transition({"status": Status.INITIALIZING.value}, secret="wrong-secret")
        self.assertEqual(response.status_code, drf_status.HTTP_401_UNAUTHORIZED)

    def test_invalid_transition_returns_409(self) -> None:
        # queued → ready is not a valid edge.
        response = self._post_transition({"status": Status.READY.value})
        self.assertEqual(response.status_code, drf_status.HTTP_409_CONFLICT)

    def test_idempotent_terminal_callback_is_noop(self) -> None:
        Deployment.objects.filter(pk=self.deployment.pk).update(status=Deployment.Status.READY.value)
        response = self._post_transition(
            {"status": Status.READY.value, "deployment_url": "https://site.posthog-app.com"}
        )
        self.assertEqual(response.status_code, drf_status.HTTP_200_OK)

    def test_unknown_deployment_returns_404(self) -> None:
        from uuid import uuid4

        response = self.client.post(
            f"/api/internal/deployments/{uuid4()}/transitions/",
            {"status": Status.INITIALIZING.value},
            format="json",
            headers={"x-internal-api-secret": SECRET},
        )
        self.assertEqual(response.status_code, drf_status.HTTP_404_NOT_FOUND)

    def test_ready_transition_flips_project_current_deployment(self) -> None:
        # queued → initializing → building → ready
        for s in (Status.INITIALIZING, Status.BUILDING, Status.READY):
            response = self._post_transition({"status": s.value})
            self.assertEqual(response.status_code, drf_status.HTTP_200_OK, response.content)

        self.deployment_project.refresh_from_db(fields=["current_deployment"])
        self.assertEqual(self.deployment_project.current_deployment_id, self.deployment.pk)

    def test_unknown_status_value_returns_400(self) -> None:
        response = self._post_transition({"status": "frobnicated"})
        self.assertEqual(response.status_code, drf_status.HTTP_400_BAD_REQUEST)


@override_settings(INTERNAL_API_SECRET=SECRET)
class TestInternalDeploymentEvents(DeploymentsTeamScopedTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.deployment_project = DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Site",
            slug="site",
            repo_url="https://github.com/example-org/site",
        )
        self.deployment = Deployment.objects.create(
            project=self.deployment_project,
            team_id=self.team.id,
            status=Deployment.Status.BUILDING.value,
        )

    def test_creates_event_with_team_id_resolved_from_deployment(self) -> None:
        response = self.client.post(
            f"/api/internal/deployments/{self.deployment.id}/events/",
            {"event_type": "step_started", "payload": {"step": "install"}},
            format="json",
            headers={"x-internal-api-secret": SECRET},
        )
        self.assertEqual(response.status_code, drf_status.HTTP_202_ACCEPTED, response.content)

        events = DeploymentEvent.objects.filter(deployment_id=self.deployment.pk)
        self.assertEqual(events.count(), 1)
        event = events.first()
        assert event is not None
        self.assertEqual(event.event_type, "step_started")
        self.assertEqual(event.payload, {"step": "install"})
        self.assertEqual(event.team_id, self.team.id)

    def test_creates_event_without_outer_team_scope(self) -> None:
        token = set_current_team_id(None)
        try:
            response = self.client.post(
                f"/api/internal/deployments/{self.deployment.id}/events/",
                {"event_type": "step_started", "payload": {"step": "install"}},
                format="json",
                headers={"x-internal-api-secret": SECRET},
            )
        finally:
            reset_current_team_id(token)

        self.assertEqual(response.status_code, drf_status.HTTP_202_ACCEPTED, response.content)
        self.assertEqual(
            DeploymentEvent.all_teams.filter(deployment_id=self.deployment.pk, event_type="step_started").count(),
            1,
        )

    def test_missing_secret_returns_401(self) -> None:
        response = self.client.post(
            f"/api/internal/deployments/{self.deployment.id}/events/",
            {"event_type": "step_started", "payload": {}},
            format="json",
        )
        self.assertEqual(response.status_code, drf_status.HTTP_401_UNAUTHORIZED)
