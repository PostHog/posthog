import hmac
import json
import time
import base64
import hashlib
from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache.backends.locmem import LocMemCache
from django.db.models.deletion import ProtectedError
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team
from posthog.models.file_system.file_system_view_log import FileSystemViewLog
from posthog.models.user import User

from products.access_control.backend.models import AccessControl
from products.account_audits.backend.models import AccountAuditAdmission, AccountAuditCredential
from products.account_audits.backend.presentation.views import (
    AccountAuditCredentialThrottle,
    AccountAuditStartRequestSerializer,
    AccountAuditStartThrottle,
)
from products.notebooks.backend.models import Notebook
from products.skills.backend.models import LLMSkill
from products.tasks.backend.models import SandboxEnvironment, Task, TaskRun


class TestAccountAuditStartAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.secret = f"whsec_{base64.b64encode(b'a' * 32).decode()}"
        self.credential = AccountAuditCredential.objects.create(created_by=self.user, signing_secret=self.secret)
        self.skill = LLMSkill.objects.create(
            team=self.team, name="account-audit", description="Audit", body="Audit this project.", version=2
        )
        self.workflow = self.enterContext(
            patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
        )
        self.url = "/api/account_audits/start/"

    def _post(
        self,
        payload: object,
        *,
        webhook_id: str = "delivery-1",
        timestamp: str | None = None,
        signature: str | None = None,
        signing_body: bytes | None = None,
        key_id: str | None = None,
    ):
        if isinstance(payload, dict):
            payload = {
                "reason": "testing",
                "skill_project": self.team.id,
                "skill_name": "account-audit",
                **payload,
            }
        raw_body = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()
        timestamp = timestamp if timestamp is not None else str(int(time.time()))
        signed_body = signing_body if signing_body is not None else raw_body
        signature = (
            signature
            or base64.b64encode(
                hmac.new(
                    b"a" * 32,
                    webhook_id.encode() + b"." + timestamp.encode() + b"." + signed_body,
                    hashlib.sha256,
                ).digest()
            ).decode()
        )
        return self.client.post(
            self.url,
            data=raw_body,
            content_type="application/json",
            HTTP_X_POSTHOG_AUDIT_KEY=key_id or str(self.credential.public_key_id),
            HTTP_WEBHOOK_ID=webhook_id,
            HTTP_WEBHOOK_TIMESTAMP=timestamp,
            HTTP_WEBHOOK_SIGNATURE=f"v1,{signature}",
        )

    def test_rate_limits_verified_credentials_separately_from_shared_ip(self) -> None:
        cache = LocMemCache(str(uuid4()), {})
        payload = {"organization_id": str(self.organization.id)}
        with (
            patch.object(AccountAuditStartThrottle, "cache", cache),
            patch.object(AccountAuditStartThrottle, "rate", "4/minute"),
            patch.object(AccountAuditCredentialThrottle, "cache", cache),
            patch.object(AccountAuditCredentialThrottle, "rate", "1/minute"),
        ):
            self.assertEqual(self._post(payload, signature="invalid").status_code, 401)
            self.assertEqual(self._post(payload).status_code, 202)
            limited = self._post(payload, key_id=str(self.credential.public_key_id).upper())
            self.assertEqual(limited.status_code, 429)
            self.assertGreater(int(limited.headers["Retry-After"]), 0)
            self.credential = AccountAuditCredential.objects.create(created_by=self.user, signing_secret=self.secret)
            self.assertEqual(self._post(payload).status_code, 202)
            self.assertEqual(self._post(payload, signature="invalid").status_code, 429)

    def test_signed_delivery_creates_a_restricted_audit_and_reuses_the_same_run(self) -> None:
        payload = {"organization_id": str(self.organization.id), "reason": "activation-review"}
        with self.captureOnCommitCallbacks(execute=True):
            first = self._post(payload)
            other_team = Team.objects.create(organization=self.organization, name="Recently active project")
            FileSystemViewLog.objects.create(team=other_team, user=self.user, type="dashboard", ref="1")
            second = self._post(payload)

        self.assertEqual(first.status_code, 202)
        admission = AccountAuditAdmission.objects.for_team(self.team.id).get(credential=self.credential)
        self.assertEqual(first.json(), {"task_run_id": str(admission.task_run_id), "team_id": self.team.id})
        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(admission.reason, "activation-review")
        self.assertEqual((admission.skill_project, admission.skill_name), (self.team.id, self.skill.name))
        run = TaskRun.objects.select_related("task").get(id=admission.task_run_id)
        self.assertEqual(TaskRun.objects.count(), 1)
        self.workflow.assert_called_once()
        self.assertEqual(run.task.created_by_id, self.user.id)
        self.assertTrue(run.task.internal)
        self.assertEqual(run.task.origin_product, "account_audit")
        self.assertIsNone(run.task.repository)
        self.assertIn(self.skill.body, run.task.description)
        self.assertIn(admission.notebook_short_id, run.task.description)
        self.assertEqual(run.state["audit_skill_version"], self.skill.version)
        self.assertFalse(run.state["pending_dispatch"]["create_pr"])
        self.assertEqual(
            run.state["pending_dispatch"]["posthog_mcp_scopes"],
            ["user:read", "query:read", "insight:read", "notebook:read", "notebook:write"],
        )
        env = SandboxEnvironment.objects.get(id=run.state["sandbox_environment_id"])
        self.assertTrue(env.internal)
        self.assertEqual(env.network_access_level, "custom")
        self.assertEqual(env.allowed_domains, [])
        self.assertFalse(env.include_default_domains)
        listed = self.client.get(f"/api/projects/{self.team.id}/notebooks/")
        self.assertNotIn(admission.notebook_short_id, [item["short_id"] for item in listed.json()["results"]])
        notebook = self.client.get(f"/api/projects/{self.team.id}/notebooks/{admission.notebook_short_id}/")
        self.assertEqual(notebook.status_code, 200)
        listed = self.client.get(f"/api/projects/{self.team.id}/notebooks/")
        self.assertIn(admission.notebook_short_id, [item["short_id"] for item in listed.json()["results"]])
        fresh = self._post({**payload, "team_id": self.team.id}, webhook_id="delivery-2")
        self.assertEqual(fresh.status_code, 202)
        self.assertNotEqual(fresh.json()["task_run_id"], first.json()["task_run_id"])

    @parameterized.expand([(False, False, False), (False, False, True), (True, False, True), (False, True, True)])
    def test_defaults_to_the_oldest_eligible_root_project_on_tied_activity(
        self, is_demo: bool, pending_deletion: bool, has_views: bool
    ) -> None:
        self.team.is_demo = is_demo
        self.team.save(update_fields=["is_demo"])
        self.team.project.is_pending_deletion = pending_deletion
        self.team.project.save(update_fields=["is_pending_deletion"])
        next_team = Team.objects.create(organization=self.organization, name="Renamed project")
        self.skill.team = next_team
        self.skill.save(update_fields=["team"])
        child = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="Child"
        )
        if has_views:
            for team in (self.team, next_team, child):
                FileSystemViewLog.objects.create(team=team, user=self.user, type="dashboard", ref="1")
            other_user = User.objects.create(email="other-viewer@example.com")
            FileSystemViewLog.objects.create(team=child, user=other_user, type="dashboard", ref="1")
        expected_id = next_team.id if is_demo or pending_deletion else self.team.id
        response = self._post({"organization_id": str(self.organization.id), "skill_project": next_team.id})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["team_id"], expected_id)
        self.assertEqual(Task.objects.get().team_id, expected_id)

    @parameterized.expand([(30, False), (31, False), (29, True)])
    @time_machine.travel("2026-01-01T00:00:00Z", tick=False)
    def test_selects_distinct_recent_viewers_unless_a_team_is_explicit(
        self, days_ago: int, explicit_team: bool
    ) -> None:
        self.team.project.created_at = timezone.now() - timedelta(days=90)
        self.team.project.save(update_fields=["created_at"])
        active_team = Team.objects.create(organization=self.organization, name="Active project")
        other_user = User.objects.create(email="other-viewer@example.com")
        for ref in ("1", "2", "3"):
            FileSystemViewLog.objects.create(team=self.team, user=self.user, type="dashboard", ref=ref)
        for user in (self.user, other_user):
            FileSystemViewLog.objects.create(
                team=active_team,
                user=user,
                type="dashboard",
                ref="1",
                viewed_at=timezone.now() - timedelta(days=days_ago),
            )
        payload: dict[str, object] = {"organization_id": str(self.organization.id)}
        if explicit_team:
            payload["team_id"] = self.team.id
        expected_id = self.team.id if explicit_team or days_ago > 30 else active_team.id
        response = self._post(payload)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["team_id"], expected_id)
        self.assertEqual(Task.objects.get().team_id, expected_id)

    def test_rejects_an_organization_without_an_eligible_default_project(self) -> None:
        self.team.is_demo = True
        self.team.save(update_fields=["is_demo"])
        response = self._post({"organization_id": str(self.organization.id)})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Task.objects.exists())

    def test_failed_run_creation_rolls_back_and_allows_retry(self) -> None:
        payload = {"organization_id": str(self.organization.id)}
        with patch(
            "products.tasks.backend.models.TaskRun.objects.create", side_effect=RuntimeError("database unavailable")
        ):
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self._post(payload).status_code, 503)
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())
        self.assertFalse(Task.objects.exists())
        self.assertFalse(Notebook.objects.filter(team_id=self.team.id).exists())
        self.workflow.assert_not_called()
        self.assertEqual(self._post(payload).status_code, 202)
        self.assertEqual(AccountAuditAdmission.objects.unscoped().count(), 1)

    def test_rejects_invalid_missing_and_stale_signatures(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        cases = [
            ("invalid", "not-base64", None),
            ("stale", None, str(int(time.time()) - 301)),
        ]
        for name, signature, timestamp in cases:
            with self.subTest(name=name):
                self.assertEqual(self._post(payload, signature=signature, timestamp=timestamp).status_code, 401)
        response = self.client.post(
            self.url,
            data=json.dumps(payload).encode(),
            content_type="application/json",
            HTTP_X_POSTHOG_AUDIT_KEY=str(self.credential.public_key_id),
            HTTP_WEBHOOK_ID="delivery-missing-signature",
            HTTP_WEBHOOK_TIMESTAMP=str(int(time.time())),
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    def test_rejects_a_signature_for_a_different_raw_body(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        response = self._post(payload, signing_body=b'{"organization_id":"different","team_id":1}')

        self.assertEqual(response.status_code, 401)
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    @parameterized.expand([("invalid_json",), ("unsupported_field",), ("oversized",)])
    def test_rejects_invalid_request_bodies(self, problem: str) -> None:
        payload = {
            "organization_id": str(self.organization.id),
            "reason": "testing",
            "skill_project": self.team.id,
            "skill_name": self.skill.name,
        }
        body = (
            b"{"
            if problem == "invalid_json"
            else json.dumps({**payload, **({"extra": True} if problem == "unsupported_field" else {})}).encode()
        )
        if problem == "oversized":
            body += b" " * 4096
        self.assertEqual(self._post(body).status_code, 400)
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    @parameterized.expand([("US",), ("EU",)])
    def test_skips_without_ai_processing_approval(self, region: str) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        payload = {"organization_id": str(self.organization.id), "reason": "activation"}
        with (
            self.settings(CLOUD_DEPLOYMENT=region),
            patch("products.account_audits.backend.logic.service.ph_scoped_capture") as capture_context,
        ):
            first = self._post(payload)
            second = self._post(payload)
        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 204)
        capture_context.assert_called_with(region="US", event_region=region, raise_on_error=True)
        captures = capture_context.return_value.__enter__.return_value.call_args_list
        self.assertEqual(captures[0], captures[1])
        self.assertEqual(captures[0].kwargs["event"], "audit_not_run")
        self.assertEqual(
            captures[0].kwargs["properties"],
            {
                "organization_id": str(self.organization.id),
                "team_id": self.team.id,
                "reason": "no ai opt in",
                "audit_reason": "activation",
                "skill_project": self.team.id,
                "skill_name": "account-audit",
                "$insert_id": f"audit-not-run-{self.credential.public_key_id}-delivery-1",
            },
        )
        self.assertFalse(Task.objects.exists())
        self.assertFalse(Notebook.objects.filter(team_id=self.team.id).exists())
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    def test_retries_a_skipped_event_if_capture_fails(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        with patch("products.account_audits.backend.logic.service.ph_scoped_capture") as capture:
            capture.return_value.__exit__.side_effect = RuntimeError("capture unavailable")
            self.assertEqual(self._post({"organization_id": str(self.organization.id)}).status_code, 503)
            capture.return_value.__exit__.side_effect = None
            self.assertEqual(self._post({"organization_id": str(self.organization.id)}).status_code, 204)
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    def test_rejects_a_deployment_that_cannot_capture_the_completion_event(self) -> None:
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        with self.settings(CLOUD_DEPLOYMENT="DEV"):
            response = self._post(payload)

        self.assertEqual(response.status_code, 503)
        self.assertFalse(Task.objects.exists())
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    def test_rejects_when_the_audit_skill_is_unavailable_without_admitting(self) -> None:
        self.skill.delete()
        response = self._post({"organization_id": str(self.organization.id)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"], "Skill not found or unsupported. Check skill_project and skill_name."
        )
        self.assertFalse(Task.objects.exists())
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    @parameterized.expand([("another_organization",), ("child_environment",)])
    def test_rejects_an_ineligible_explicit_team(self, problem: str) -> None:
        organization_id, team_id = self.organization.id, self.team.id
        if problem == "another_organization":
            other_org = Organization.objects.create(name="Other organization", is_ai_data_processing_approved=True)
            Team.objects.create(organization=other_org, name="Other team")
            organization_id = other_org.id
        else:
            team_id = Team.objects.create(
                organization=self.organization, project=self.team.project, parent_team=self.team, name="Child"
            ).id
        payload = {"organization_id": str(organization_id), "team_id": team_id}
        response = self._post(payload)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Task.objects.exists())

    def test_rejects_when_no_team_actor_is_available(self) -> None:
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self._post({"organization_id": str(self.organization.id), "team_id": self.team.id})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Task.objects.exists())

    @parameterized.expand([("team_id",), ("reason",), ("skill_project",), ("skill_name",)])
    def test_rejects_a_repeated_delivery_with_changed_parameters(self, field: str) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        payload = {"organization_id": str(self.organization.id), "team_id": self.team.id}
        changed_payload = {
            **payload,
            field: other_team.id if field in ("team_id", "skill_project") else "another-audit",
        }
        self.assertEqual(self._post(payload).status_code, 202)
        response = self._post(changed_payload)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "This delivery ID has another audit request.")
        self.assertEqual(TaskRun.objects.count(), 1)
        self.assertEqual(AccountAuditAdmission.objects.unscoped().count(), 1)

    @parameterized.expand([("inactive",), ("not_staff",), ("deleted",)])
    def test_audit_uses_a_private_skill_independently_of_credential_creator(self, condition: str) -> None:
        creator = User.objects.create(email="audit-creator@example.com", is_staff=True)
        self.credential.created_by = creator
        self.credential.save(update_fields=["created_by"])
        if condition == "deleted":
            creator.delete()
        else:
            User.objects.filter(pk=creator.pk).update(**{"is_active" if condition == "inactive" else "is_staff": False})
        skill_org = Organization.objects.create(
            name="Skill organization", available_product_features=[{"key": AvailableFeature.ACCESS_CONTROL}]
        )
        skill_team = Team.objects.create(organization=skill_org, name="Private skills")
        skill = LLMSkill.objects.create(
            team=skill_team, name="account-audit", description="Audit", body="# Audit\n", is_latest=True
        )
        AccessControl.objects.create(
            team=skill_team, resource="project", resource_id=str(skill_team.id), access_level="none"
        )
        AccessControl.objects.create(
            team=skill_team, resource="llm_skill", resource_id=str(skill.id), access_level="none"
        )
        response = self._post({"organization_id": str(self.organization.id), "skill_project": skill_team.id})

        self.assertEqual(response.status_code, 202)
        self.assertIn(skill.body, Task.objects.get().description)
        self.assertEqual(AccountAuditAdmission.objects.unscoped().get().skill_project, skill_team.id)

    @parameterized.expand([("revoked",), ("unknown_key",), ("wrong_secret",)])
    def test_rejects_an_ineligible_destination_credential(self, condition: str) -> None:
        if condition == "revoked":
            AccountAuditCredential.objects.filter(pk=self.credential.pk).update(is_active=False)
        elif condition == "unknown_key":
            AccountAuditCredential.objects.filter(pk=self.credential.pk).update(public_key_id=uuid4())
        else:
            AccountAuditCredential.objects.filter(pk=self.credential.pk).update(
                signing_secret=f"whsec_{base64.b64encode(b'b' * 32).decode()}"
            )
        response = self._post({"organization_id": str(self.organization.id)})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(Task.objects.exists())
        self.assertFalse(AccountAuditAdmission.objects.unscoped().exists())

    def test_preserves_historic_admissions_when_a_creator_or_credential_is_deleted(self) -> None:
        creator = User.objects.create_user(email="audit-creator@example.com", password=None, first_name="Audit")
        credential = AccountAuditCredential.objects.create(created_by=creator, signing_secret=self.secret)
        admission = AccountAuditAdmission.objects.unscoped().create(
            credential=credential,
            task_run_id=uuid4(),
            webhook_id="delivery-1",
            organization_id=self.organization.id,
            team_id=self.team.id,
        )

        creator.delete()
        credential.refresh_from_db()
        self.assertIsNone(credential.created_by)
        with self.assertRaises(ProtectedError):
            credential.delete()
        self.assertTrue(AccountAuditAdmission.objects.unscoped().filter(pk=admission.pk).exists())


class TestAccountAuditRequestValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("unknown_field", {"extra": True}),
            ("boolean_project", {"skill_project": True}),
            ("string_team", {"team_id": "1"}),
            ("null_team", {"team_id": None}),
            ("numeric_reason", {"reason": 1}),
            ("numeric_skill", {"skill_name": 1}),
        ]
    )
    def test_rejects_values_that_drf_would_coerce(self, _name: str, changes: dict[str, object]) -> None:
        serializer = AccountAuditStartRequestSerializer(
            data={
                "organization_id": str(uuid4()),
                "reason": "testing",
                "skill_project": 1,
                "skill_name": "account-audit",
                **changes,
            }
        )
        self.assertFalse(serializer.is_valid())
