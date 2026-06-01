"""Integration tests for finalize_success — the on-commit side effects
that run when a deployment flips to READY.

We invoke `finalize_success.execute(...)` directly rather than going
through `update_status.execute` because the `transaction.on_commit`
callback doesn't fire inside Django's per-test transaction. This lets
us assert the side effects in isolation.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models.annotation import Annotation

from products.deployments.backend.models import Deployment, DeploymentEvent, DeploymentProject
from products.deployments.backend.services import finalize_success
from products.deployments.backend.test._helpers import DeploymentsTeamScopedTestMixin
from products.error_tracking.backend.models import ErrorTrackingRelease


class TestFinalizeSuccess(DeploymentsTeamScopedTestMixin, APIBaseTest):
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
            status=Deployment.Status.READY.value,
            commit_sha="abcdef1234567890abcdef1234567890abcdef12",
            commit_message="feat: ship the new pricing page",
            commit_author_name="Alice",
            commit_author_email="alice@example.com",
            branch="main",
            deployment_url="https://abcdef0.site.posthog-app.com",
            started_at=timezone.now(),
            finished_at=timezone.now(),
        )

    def _execute(self, *, screenshot=None) -> None:
        # Mock ph_scoped_capture — we test that it's called with the right
        # event/properties, but we don't want it to actually call out.
        with patch("products.deployments.backend.services.finalize_success.ph_scoped_capture") as mock_capture_cm:
            mock_capture = MagicMock()
            mock_capture_cm.return_value.__enter__.return_value = mock_capture
            finalize_success.execute(
                deployment_id=self.deployment.pk,
                screenshot=screenshot,
            )
            self._mock_capture = mock_capture
            self._mock_capture_cm = mock_capture_cm

    def test_creates_project_annotation_with_github_creation_type(self) -> None:
        screenshot = MagicMock()
        screenshot.capture.return_value = None
        self._execute(screenshot=screenshot)

        annotations = Annotation.objects.filter(team_id=self.team.id)
        self.assertEqual(annotations.count(), 1)
        annotation = annotations.first()
        assert annotation is not None
        self.assertEqual(annotation.scope, Annotation.Scope.PROJECT)
        self.assertEqual(annotation.creation_type, Annotation.CreationType.GITHUB)
        self.assertEqual(annotation.organization_id, self.organization.id)
        # Content: first 80 chars of message + (sha7)
        self.assertIn("feat: ship the new pricing page", annotation.content or "")
        self.assertIn("abcdef1", annotation.content or "")

    def test_creates_error_tracking_release_with_deployment_id_hash(self) -> None:
        screenshot = MagicMock()
        screenshot.capture.return_value = None
        self._execute(screenshot=screenshot)

        releases = ErrorTrackingRelease.objects.filter(team_id=self.team.id)
        self.assertEqual(releases.count(), 1)
        release = releases.first()
        assert release is not None
        self.assertEqual(release.hash_id, str(self.deployment.id))
        self.assertEqual(release.version, "abcdef1")
        self.assertEqual(release.project, self.deployment_project.cloudflare_project_name)

    def test_emits_deployment_event_via_ph_scoped_capture(self) -> None:
        screenshot = MagicMock()
        screenshot.capture.return_value = None
        self._execute(screenshot=screenshot)

        self._mock_capture.assert_called_once()
        call_args = self._mock_capture.call_args
        self.assertEqual(call_args.kwargs["event"], "$deployment")
        properties = call_args.kwargs["properties"]
        self.assertEqual(properties["deployment_id"], str(self.deployment.id))
        self.assertEqual(properties["commit_sha"], self.deployment.commit_sha)
        self.assertEqual(properties["deployment_url"], self.deployment.deployment_url)

    def test_screenshot_success_persists_preview_url(self) -> None:
        screenshot = MagicMock()
        screenshot.capture.return_value = "https://cdn.example/preview.png"
        self._execute(screenshot=screenshot)

        self.deployment.refresh_from_db(fields=["preview_image_url"])
        self.assertEqual(self.deployment.preview_image_url, "https://cdn.example/preview.png")

        events = DeploymentEvent.objects.filter(deployment_id=self.deployment.pk, event_type="preview_captured")
        self.assertEqual(events.count(), 1)

    def test_screenshot_failure_emits_failed_event_but_does_not_block(self) -> None:
        screenshot = MagicMock()
        screenshot.capture.return_value = None
        self._execute(screenshot=screenshot)

        # Status stayed READY — failure didn't roll back.
        self.deployment.refresh_from_db()
        self.assertEqual(self.deployment.status, Deployment.Status.READY.value)
        self.assertEqual(self.deployment.preview_image_url, "")

        events = DeploymentEvent.objects.filter(deployment_id=self.deployment.pk, event_type="preview_capture_failed")
        self.assertEqual(events.count(), 1)

    def test_idempotent_release_creation(self) -> None:
        # Running finalize twice should not create a second release row —
        # the internal endpoint must be safe against Temporal's at-least-once
        # delivery semantics.
        screenshot = MagicMock()
        screenshot.capture.return_value = None
        self._execute(screenshot=screenshot)
        self._execute(screenshot=screenshot)

        releases = ErrorTrackingRelease.objects.filter(team_id=self.team.id, hash_id=str(self.deployment.id))
        self.assertEqual(releases.count(), 1)

    def test_runs_without_outer_team_scope(self) -> None:
        # Regression: in production the `transaction.on_commit` callback
        # fires AFTER the request transaction commits and AFTER the
        # request's team scope has been reset. finalize_success.execute
        # must enter scope itself, otherwise every successful deploy
        # crashes with TeamScopeError.
        from posthog.models.scoping import _current_team_id

        screenshot = MagicMock()
        screenshot.capture.return_value = "https://cdn.example/preview.png"

        # Reset the outer scope set by DeploymentsTeamScopedTestMixin —
        # mimic the production on_commit path where no scope is active.
        token = _current_team_id.set(None)
        try:
            with patch("products.deployments.backend.services.finalize_success.ph_scoped_capture") as cap:
                cap.return_value.__enter__.return_value = MagicMock()
                finalize_success.execute(
                    deployment_id=self.deployment.pk,
                    screenshot=screenshot,
                )
        finally:
            _current_team_id.reset(token)

        # Both scoped writes should have succeeded under the in-function scope.
        self.deployment.refresh_from_db(fields=["preview_image_url"])
        self.assertEqual(self.deployment.preview_image_url, "https://cdn.example/preview.png")
        self.assertEqual(
            DeploymentEvent.all_teams.filter(deployment_id=self.deployment.pk).count(),
            1,
        )
