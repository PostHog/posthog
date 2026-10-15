from datetime import timedelta
from uuid import UUID

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models import User

from products.account_audits.backend.logic.execution import finish_account_audit
from products.account_audits.backend.models import AccountAuditAdmission, AccountAuditCredential
from products.account_audits.backend.tasks.tasks import reconcile_account_audits
from products.notebooks.backend.models import Notebook
from products.tasks.backend.models import Task, TaskRun


@override_settings(SITE_URL="http://testserver")
@time_machine.travel("2026-09-01T12:00:00Z", tick=False)
class TestAuditExecution(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Audit",
            description="Audit.",
            origin_product=Task.OriginProduct.ACCOUNT_AUDIT,
            internal=True,
        )
        self.notebook = Notebook.objects.filter(team_id=self.team.id).create(
            team=self.team,
            created_by=self.user,
            title="Audit",
            visibility="internal",
            content={
                "type": "doc",
                "content": [{"type": "ph-markdown-notebook", "attrs": {"markdown": "# Audit\n\nFindings."}}],
            },
        )
        self.task_run = TaskRun.objects.create(
            task=self.task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            environment=TaskRun.Environment.CLOUD,
            completed_at=timezone.now() - timedelta(minutes=4),
            output={"notebook_short_id": self.notebook.short_id},
            state={"unprocessed_request_ids": [], "token_cost": {"claude": {"anthropic": {"cost_microusd": 270000}}}},
        )
        credential = AccountAuditCredential.objects.create(created_by=self.user, signing_secret="unused")
        self.admission = AccountAuditAdmission.objects.for_team(self.team.id).create(
            credential=credential,
            webhook_id="delivery",
            organization_id=self.organization.id,
            team_id=self.team.id,
            task_run_id=self.task_run.id,
            notebook_short_id=self.notebook.short_id,
            reason="testing",
            skill_project=self.team.id,
            skill_name="custom-audit",
        )
        self.capture_context = self.enterContext(
            patch("products.account_audits.backend.logic.execution.ph_scoped_capture")
        )
        self.capture = self.capture_context.return_value.__enter__.return_value

    def finish(self) -> None:
        self.task_run.save(update_fields=["status", "completed_at", "state", "output"])
        if self.notebook.pk:
            self.notebook.save(update_fields=["content", "created_by"])
        finish_account_audit(team_id=self.team.id, task_run_id=self.task_run.id)
        self.admission.refresh_from_db()

    @parameterized.expand([("US", 0), ("EU", 27)])
    def test_emits_verified_result_with_native_cost_once(self, region: str, token_cost: int) -> None:
        self.task_run.state["token_cost"]["claude"]["anthropic"]["cost_microusd"] = token_cost * 10000
        with self.settings(CLOUD_DEPLOYMENT=region):
            self.finish()
            self.finish()
        self.capture_context.assert_called_once_with(region="US", event_region=region, raise_on_error=True)
        self.capture.assert_called_once()
        event = self.capture.call_args.kwargs
        self.assertEqual(event["event"], "account_audit_finished")
        self.assertEqual(
            event["properties"],
            {
                "organization_id": str(self.organization.id),
                "team_id": self.team.id,
                "notebook_url": f"http://testserver/project/{self.team.id}/notebooks/{self.notebook.short_id}",
                "reason": "testing",
                "skill_project": self.team.id,
                "skill_name": "custom-audit",
                "token_cost_cents": token_cost,
                "$insert_id": f"account-audit-finished-{self.task_run.id}",
            },
        )
        self.assertIsNotNone(self.admission.finalized_at)

    @parameterized.expand([("failed",), ("cancelled",), ("in_progress",)])
    def test_no_success_event_for_other_statuses(self, status: str) -> None:
        self.task_run.status = status
        self.finish()
        self.capture.assert_not_called()
        self.assertEqual(self.admission.finalized_at is not None, status != "in_progress")

    @parameterized.expand(
        [
            ("empty",),
            ("heading",),
            ("missing",),
            ("wrong_output",),
            ("wrong_creator",),
            ("wrong_origin",),
            ("no_consent",),
        ]
    )
    def test_rejects_unverified_results(self, problem: str) -> None:
        if problem == "empty":
            self.notebook.content = {"type": "doc", "content": []}
        elif problem == "heading":
            self.notebook.content["content"][0]["attrs"]["markdown"] = "# Audit"
        elif problem == "missing":
            self.notebook.delete()
        elif problem == "wrong_output":
            self.task_run.output = {"notebook_short_id": "another"}
        elif problem == "wrong_creator":
            self.notebook.created_by = User.objects.create(email="other-author@example.com")
        elif problem == "wrong_origin":
            self.task.origin_product = Task.OriginProduct.USER_CREATED
            self.task.save(update_fields=["origin_product"])
        else:
            self.organization.is_ai_data_processing_approved = False
            self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.finish()
        self.capture.assert_not_called()
        self.assertIsNotNone(self.admission.finalized_at)

    @parameterized.expand([("settled",), ("pending",)])
    def test_waits_for_callbacks_then_reports_native_cost(self, accounting: str) -> None:
        self.task_run.completed_at = timezone.now()
        self.task_run.state["token_cost"] = {}
        self.finish()
        self.assertIsNone(self.admission.finalized_at)
        self.capture.assert_not_called()
        self.task_run.state["unprocessed_request_ids"] = ["request-1"]
        if accounting == "settled":
            self.task_run.state["unprocessed_request_ids"] = []
            self.task_run.state["token_cost"] = {"claude": {"anthropic": {"cost_microusd": 270000}}}
            self.finish()
            self.capture.assert_not_called()
        with time_machine.travel(timezone.now() + timedelta(minutes=3), tick=False):
            self.finish()
        self.assertEqual(
            self.capture.call_args.kwargs["properties"]["token_cost_cents"], 27 if accounting == "settled" else None
        )
        self.assertIsNotNone(self.admission.finalized_at)

    @parameterized.expand([("project",), ("organization",)])
    def test_deletes_admission_with_its_tenant(self, tenant: str) -> None:
        if tenant == "project":
            self.team.project.delete()
        else:
            self.organization.delete()
        finish_account_audit(team_id=self.team.id, task_run_id=self.task_run.id)
        self.assertFalse(AccountAuditAdmission.objects.unscoped().filter(pk=self.admission.pk).exists())
        self.capture.assert_not_called()

    def test_periodic_scan_retries_capture_failure_and_stops_after_finalization(self) -> None:
        self.capture.side_effect = RuntimeError("capture unavailable")
        with self.assertRaises(RuntimeError):
            self.finish()
        self.assertIsNone(self.admission.finalized_at)
        self.capture.side_effect = None
        with patch(
            "products.account_audits.backend.tasks.tasks.finalize_account_audit.delay",
            side_effect=lambda team_id, run_id: finish_account_audit(team_id=team_id, task_run_id=UUID(run_id)),
        ) as enqueue:
            reconcile_account_audits()
            self.admission.refresh_from_db()
            self.assertIsNotNone(self.admission.finalized_at)
            reconcile_account_audits()
        enqueue.assert_called_once_with(self.team.id, str(self.task_run.id))
