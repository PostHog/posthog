"""Service-layer tests with stubbed adapters.

Each service exposes `execute(...)` and accepts adapter overrides as
keyword args so tests can substitute fakes without monkeypatching. We
verify the orchestration around the ORM and the on_commit side-effect
scheduling — finalize_success / finalize_failure themselves are tested
separately under test_finalize_success.py.
"""

from __future__ import annotations

from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from django.utils import timezone

from products.deployments.backend.adapters import NullCloudflareAdapter
from products.deployments.backend.adapters.github import NullGitHubAdapter
from products.deployments.backend.adapters.temporal import NullWorkflowAdapter
from products.deployments.backend.domain.status import Status
from products.deployments.backend.domain.trigger import ErrorStep, TriggerKind
from products.deployments.backend.models import Deployment, DeploymentEvent, DeploymentProject
from products.deployments.backend.services import (
    cancel,
    create_deployment,
    redeploy,
    refresh_preview,
    rollback,
    update_status,
)
from products.deployments.backend.test._helpers import DeploymentsTeamScopedTestMixin


class _BaseServicesTest(DeploymentsTeamScopedTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.deployment_project = DeploymentProject.objects.create(
            team_id=self.team.id,
            name="Site",
            slug="site",
            repo_url="https://github.com/example-org/site",
            default_branch="main",
            cloudflare_project_name=f"{self.team.id}-site",
            subdomain="site.posthog-app.com",
            cloudflare_ready_at=timezone.now(),
        )


class TestCreateDeployment(_BaseServicesTest):
    def test_creates_row_and_persists_workflow_handle(self) -> None:
        deployment = create_deployment.execute(
            create_deployment.CreateDeploymentInput(
                project_id=str(self.deployment_project.id),
                team_id=self.team.id,
                triggered_by_user_id=self.user.id,
                trigger_kind=TriggerKind.MANUAL,
                commit_sha=None,
                branch=None,
            ),
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        self.assertEqual(deployment.status, Deployment.Status.QUEUED.value)
        self.assertEqual(deployment.project_id, self.deployment_project.id)
        self.assertEqual(deployment.team_id, self.team.id)
        self.assertEqual(deployment.trigger_kind, TriggerKind.MANUAL.value)
        # NullWorkflowAdapter assigns `deployment-{id}` as workflow_id —
        # the row must round-trip it after the post-insert update().
        self.assertTrue(deployment.temporal_workflow_id.startswith("deployment-"))
        self.assertTrue(deployment.temporal_run_id)

    def test_second_concurrent_create_raises_active_deployment_exists(self) -> None:
        first = create_deployment.execute(
            create_deployment.CreateDeploymentInput(
                project_id=str(self.deployment_project.id),
                team_id=self.team.id,
                triggered_by_user_id=self.user.id,
                trigger_kind=TriggerKind.MANUAL,
                commit_sha=None,
                branch=None,
            ),
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        with self.assertRaises(create_deployment.ActiveDeploymentExists) as cm:
            create_deployment.execute(
                create_deployment.CreateDeploymentInput(
                    project_id=str(self.deployment_project.id),
                    team_id=self.team.id,
                    triggered_by_user_id=self.user.id,
                    trigger_kind=TriggerKind.MANUAL,
                    commit_sha=None,
                    branch=None,
                ),
                cloudflare=NullCloudflareAdapter(),
                github=NullGitHubAdapter(),
                workflow=NullWorkflowAdapter(),
            )
        self.assertEqual(cm.exception.active_deployment_id, str(first.id))

    def test_workflow_dispatch_failure_marks_row_error(self) -> None:
        # Regression: if start_build raises (Temporal unreachable), the
        # row must NOT be left in QUEUED with no workflow id — it has to
        # be flipped to ERROR(error_step=dispatch) and the caller gets a
        # typed WorkflowDispatchFailed they can map to 502.
        workflow = MagicMock()
        workflow.start_build.side_effect = RuntimeError("temporal is down")
        with self.assertRaises(create_deployment.WorkflowDispatchFailed) as cm:
            create_deployment.execute(
                create_deployment.CreateDeploymentInput(
                    project_id=str(self.deployment_project.id),
                    team_id=self.team.id,
                    triggered_by_user_id=self.user.id,
                    trigger_kind=TriggerKind.MANUAL,
                    commit_sha=None,
                    branch=None,
                ),
                cloudflare=NullCloudflareAdapter(),
                github=NullGitHubAdapter(),
                workflow=workflow,
            )
        # The orphan deployment id is surfaced for operators.
        self.assertTrue(cm.exception.deployment_id)
        orphan = Deployment.objects.get(pk=cm.exception.deployment_id)
        self.assertEqual(orphan.status, Deployment.Status.ERROR.value)
        self.assertEqual(orphan.error_step, "dispatch")
        self.assertIn("temporal is down", orphan.error_message)
        self.assertIsNotNone(orphan.finished_at)

    def test_terminal_deployment_does_not_block_new_one(self) -> None:
        first = create_deployment.execute(
            create_deployment.CreateDeploymentInput(
                project_id=str(self.deployment_project.id),
                team_id=self.team.id,
                triggered_by_user_id=self.user.id,
                trigger_kind=TriggerKind.MANUAL,
                commit_sha=None,
                branch=None,
            ),
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        # Park the first row in a terminal state.
        Deployment.objects.filter(pk=first.pk).update(status=Deployment.Status.ERROR.value)
        second = create_deployment.execute(
            create_deployment.CreateDeploymentInput(
                project_id=str(self.deployment_project.id),
                team_id=self.team.id,
                triggered_by_user_id=self.user.id,
                trigger_kind=TriggerKind.MANUAL,
                commit_sha=None,
                branch=None,
            ),
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(second.status, Deployment.Status.QUEUED.value)


class TestUpdateStatus(_BaseServicesTest):
    def _make_queued(self) -> Deployment:
        return create_deployment.execute(
            create_deployment.CreateDeploymentInput(
                project_id=str(self.deployment_project.id),
                team_id=self.team.id,
                triggered_by_user_id=self.user.id,
                trigger_kind=TriggerKind.MANUAL,
                commit_sha=None,
                branch=None,
            ),
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )

    def test_walks_the_happy_path(self) -> None:
        deployment = self._make_queued()
        update_status.execute(update_status.UpdateStatusInput(deployment_id=deployment.id, status=Status.INITIALIZING))
        deployment.refresh_from_db()
        self.assertEqual(deployment.status, Deployment.Status.INITIALIZING.value)
        self.assertIsNotNone(deployment.started_at)

        update_status.execute(update_status.UpdateStatusInput(deployment_id=deployment.id, status=Status.BUILDING))
        deployment.refresh_from_db()
        self.assertEqual(deployment.status, Deployment.Status.BUILDING.value)

        update_status.execute(
            update_status.UpdateStatusInput(
                deployment_id=deployment.id,
                status=Status.READY,
                deployment_url="https://abcdef.site.posthog-app.com",
                cloudflare_deployment_id="cf-abcdef",
            )
        )
        deployment.refresh_from_db()
        self.assertEqual(deployment.status, Deployment.Status.READY.value)
        self.assertEqual(deployment.deployment_url, "https://abcdef.site.posthog-app.com")
        self.assertEqual(deployment.cloudflare_deployment_id, "cf-abcdef")
        self.assertIsNotNone(deployment.finished_at)

        # On READY, project.current_deployment must flip to this row.
        self.deployment_project.refresh_from_db(fields=["current_deployment"])
        self.assertEqual(self.deployment_project.current_deployment_id, deployment.pk)

    def test_duplicate_terminal_callback_is_noop(self) -> None:
        deployment = self._make_queued()
        update_status.execute(update_status.UpdateStatusInput(deployment_id=deployment.id, status=Status.INITIALIZING))
        update_status.execute(update_status.UpdateStatusInput(deployment_id=deployment.id, status=Status.BUILDING))
        update_status.execute(update_status.UpdateStatusInput(deployment_id=deployment.id, status=Status.READY))

        deployment.refresh_from_db()
        first_finished_at = deployment.finished_at

        # Second `ready` callback — should be a quiet no-op, not raise.
        update_status.execute(update_status.UpdateStatusInput(deployment_id=deployment.id, status=Status.READY))
        deployment.refresh_from_db()
        self.assertEqual(deployment.status, Deployment.Status.READY.value)
        self.assertEqual(deployment.finished_at, first_finished_at)

    def test_invalid_transition_raises(self) -> None:
        from products.deployments.backend.domain.status import InvalidStatusTransition

        deployment = self._make_queued()
        # queued → ready is not a valid edge in the graph.
        with self.assertRaises(InvalidStatusTransition):
            update_status.execute(update_status.UpdateStatusInput(deployment_id=deployment.id, status=Status.READY))

    def test_error_step_recorded(self) -> None:
        deployment = self._make_queued()
        update_status.execute(update_status.UpdateStatusInput(deployment_id=deployment.id, status=Status.INITIALIZING))
        update_status.execute(
            update_status.UpdateStatusInput(
                deployment_id=deployment.id,
                status=Status.ERROR,
                error_message="Build exploded",
                error_step=ErrorStep.BUILD,
            )
        )
        deployment.refresh_from_db()
        self.assertEqual(deployment.status, Deployment.Status.ERROR.value)
        self.assertEqual(deployment.error_step, ErrorStep.BUILD.value)
        self.assertEqual(deployment.error_message, "Build exploded")


class TestRollback(_BaseServicesTest):
    def test_creates_new_row_with_rollback_kind_and_lineage(self) -> None:
        original = create_deployment.execute(
            create_deployment.CreateDeploymentInput(
                project_id=str(self.deployment_project.id),
                team_id=self.team.id,
                triggered_by_user_id=self.user.id,
                trigger_kind=TriggerKind.MANUAL,
                commit_sha="abc1234567890abcdef0",
                branch=None,
            ),
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        Deployment.objects.filter(pk=original.pk).update(status=Deployment.Status.READY.value)

        rolled_back = rollback.execute(
            deployment_id=str(original.id),
            team_id=self.team.id,
            triggered_by_user_id=self.user.id,
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        self.assertEqual(rolled_back.trigger_kind, TriggerKind.ROLLBACK.value)
        self.assertEqual(rolled_back.triggered_by_deployment_id, original.pk)
        self.assertEqual(rolled_back.commit_sha, original.commit_sha)


class TestRedeploy(_BaseServicesTest):
    def test_redeploy_clones_commit(self) -> None:
        original = create_deployment.execute(
            create_deployment.CreateDeploymentInput(
                project_id=str(self.deployment_project.id),
                team_id=self.team.id,
                triggered_by_user_id=self.user.id,
                trigger_kind=TriggerKind.MANUAL,
                commit_sha="deadbeef1234567890ab",
                branch="release",
            ),
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        Deployment.objects.filter(pk=original.pk).update(status=Deployment.Status.READY.value)

        new = redeploy.execute(
            deployment_id=str(original.id),
            team_id=self.team.id,
            triggered_by_user_id=self.user.id,
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        self.assertEqual(new.trigger_kind, TriggerKind.REDEPLOY.value)
        self.assertEqual(new.triggered_by_deployment_id, original.pk)
        self.assertEqual(new.commit_sha, original.commit_sha)


class TestCancel(_BaseServicesTest):
    def test_cancel_signals_workflow(self) -> None:
        deployment = create_deployment.execute(
            create_deployment.CreateDeploymentInput(
                project_id=str(self.deployment_project.id),
                team_id=self.team.id,
                triggered_by_user_id=self.user.id,
                trigger_kind=TriggerKind.MANUAL,
                commit_sha=None,
                branch=None,
            ),
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        workflow = MagicMock()
        signalled = cancel.execute(
            deployment_id=str(deployment.id),
            team_id=self.team.id,
            workflow=workflow,
        )
        workflow.signal_cancel.assert_called_once_with(workflow_id=deployment.temporal_workflow_id)
        self.assertTrue(signalled)

    def test_cancel_without_workflow_id_flips_row_directly(self) -> None:
        # Orphan case: the row never got a temporal_workflow_id (e.g.
        # start_build crashed mid-dispatch). cancel must NOT silently no-op
        # — it should walk the state machine to CANCELLED so the row
        # doesn't sit QUEUED forever.
        deployment = create_deployment.execute(
            create_deployment.CreateDeploymentInput(
                project_id=str(self.deployment_project.id),
                team_id=self.team.id,
                triggered_by_user_id=self.user.id,
                trigger_kind=TriggerKind.MANUAL,
                commit_sha=None,
                branch=None,
            ),
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        Deployment.objects.filter(pk=deployment.pk).update(temporal_workflow_id="")
        workflow = MagicMock()
        signalled = cancel.execute(
            deployment_id=str(deployment.id),
            team_id=self.team.id,
            workflow=workflow,
        )
        workflow.signal_cancel.assert_not_called()
        self.assertFalse(signalled)
        deployment.refresh_from_db()
        self.assertEqual(deployment.status, Deployment.Status.CANCELLED.value)

    def test_cancel_terminal_deployment_raises(self) -> None:
        deployment = create_deployment.execute(
            create_deployment.CreateDeploymentInput(
                project_id=str(self.deployment_project.id),
                team_id=self.team.id,
                triggered_by_user_id=self.user.id,
                trigger_kind=TriggerKind.MANUAL,
                commit_sha=None,
                branch=None,
            ),
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        Deployment.objects.filter(pk=deployment.pk).update(status=Deployment.Status.READY.value)
        with self.assertRaises(cancel.DeploymentNotCancellable):
            cancel.execute(
                deployment_id=str(deployment.id),
                team_id=self.team.id,
                workflow=MagicMock(),
            )


class TestRefreshPreview(_BaseServicesTest):
    def test_capture_success_writes_image_url_and_event(self) -> None:
        deployment = create_deployment.execute(
            create_deployment.CreateDeploymentInput(
                project_id=str(self.deployment_project.id),
                team_id=self.team.id,
                triggered_by_user_id=self.user.id,
                trigger_kind=TriggerKind.MANUAL,
                commit_sha=None,
                branch=None,
            ),
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        Deployment.objects.filter(pk=deployment.pk).update(
            status=Deployment.Status.READY.value,
            deployment_url="https://site.posthog-app.com",
        )

        screenshot = MagicMock()
        screenshot.capture.return_value = "https://cdn.example/preview.png"

        updated = refresh_preview.execute(
            deployment_id=str(deployment.id),
            team_id=self.team.id,
            screenshot=screenshot,
        )
        self.assertEqual(updated.preview_image_url, "https://cdn.example/preview.png")

        events = list(DeploymentEvent.objects.filter(deployment_id=deployment.pk).values_list("event_type", flat=True))
        self.assertIn("preview_captured", events)

    def test_capture_failure_emits_failed_event(self) -> None:
        deployment = create_deployment.execute(
            create_deployment.CreateDeploymentInput(
                project_id=str(self.deployment_project.id),
                team_id=self.team.id,
                triggered_by_user_id=self.user.id,
                trigger_kind=TriggerKind.MANUAL,
                commit_sha=None,
                branch=None,
            ),
            cloudflare=NullCloudflareAdapter(),
            github=NullGitHubAdapter(),
            workflow=NullWorkflowAdapter(),
        )
        Deployment.objects.filter(pk=deployment.pk).update(
            status=Deployment.Status.READY.value,
            deployment_url="https://site.posthog-app.com",
        )

        screenshot = MagicMock()
        screenshot.capture.return_value = None

        refresh_preview.execute(
            deployment_id=str(deployment.id),
            team_id=self.team.id,
            screenshot=screenshot,
        )
        events = list(DeploymentEvent.objects.filter(deployment_id=deployment.pk).values_list("event_type", flat=True))
        self.assertIn("preview_capture_failed", events)
