"""
Focused tests for the AgentApplicationViewSet approval-gated endpoints.

The runtime side (intercept, store, wake, sweep) is covered by the e2e
harness in services/agent-tests/src/cases/approval-gated.test.ts. These
tests guard the Django-side concerns that don't go through the harness:

  - Team-admin-only auth on list / retrieve / decide (plan §6.1).
  - The Django view forwards body + path params to the janitor and
    surfaces the upstream response intact.
  - Ownership cross-check rejects approval ids that belong to a sibling
    application.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from ..models import AgentApplication


class TestApprovalEndpointsAuth(APIBaseTest):
    databases = {
        "default",
        "persons_db_writer",
        "persons_db_reader",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="gated-agent",
            name="Gated Agent",
            description="",
        )
        self.url_list = f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/approvals/"
        self.approval_id = "00000000-0000-4000-8000-000000000001"
        self.url_detail = f"{self.url_list}{self.approval_id}/"
        self.url_decide = f"{self.url_list}{self.approval_id}/decide/"

    def _set_org_level(self, level: OrganizationMembership.Level) -> None:
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = level
        membership.save()

    def test_non_admin_cannot_list_approvals(self) -> None:
        self._set_org_level(OrganizationMembership.Level.MEMBER)
        resp = self.client.get(self.url_list)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_admin_cannot_decide(self) -> None:
        self._set_org_level(OrganizationMembership.Level.MEMBER)
        resp = self.client.post(
            self.url_decide,
            {"decision": "approve"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_admin_list_forwards_to_janitor(self, mock_janitor) -> None:
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        mock_janitor.return_value.list_approvals.return_value = {"results": []}
        resp = self.client.get(self.url_list, {"state": "queued"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_janitor.return_value.list_approvals.assert_called_once_with(
            str(self.application.id),
            state="queued",
            limit=None,
            offset=None,
        )

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_admin_decide_forwards_decision_payload(self, mock_janitor) -> None:
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        mock_janitor.return_value.get_approval.return_value = {
            "id": self.approval_id,
            "application_id": str(self.application.id),
            "approver_scope": {"allow_agent_approver": False},
        }
        mock_janitor.return_value.decide_approval.return_value = {"ok": True, "state": "approving"}
        resp = self.client.post(
            self.url_decide,
            {"decision": "approve", "reason": "looks good"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # The pre-flight read is tenant-scoped to the application in the URL.
        mock_janitor.return_value.get_approval.assert_called_once_with(
            self.approval_id, application_id=str(self.application.id)
        )
        mock_janitor.return_value.decide_approval.assert_called_once_with(
            self.approval_id,
            decision="approve",
            decided_by=str(self.user.uuid),
            edited_args=None,
            reason="looks good",
            application_id=str(self.application.id),
        )

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_admin_cannot_decide_approval_for_other_application(self, mock_janitor) -> None:
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        other_app = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="other-agent",
            name="Other Agent",
            description="",
        )
        # Janitor reports the approval belongs to `other_app`, but we asked
        # via the URL for `self.application`. The view must reject — otherwise
        # an admin on team A could decide approvals on any agent in the same
        # janitor DB just by mutating the URL.
        mock_janitor.return_value.get_approval.return_value = {
            "id": self.approval_id,
            "application_id": str(other_app.id),
            "approver_scope": {"allow_agent_approver": False},
        }
        resp = self.client.post(
            self.url_decide,
            {"decision": "approve"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        mock_janitor.return_value.decide_approval.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_decide_validates_required_fields(self, mock_janitor) -> None:
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        resp = self.client.post(self.url_decide, {}, format="json")
        # `decision` is required → 400.
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        mock_janitor.return_value.decide_approval.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_personal_api_key_cannot_decide_when_agent_approver_disallowed(self, mock_janitor) -> None:
        # An admin's Personal API key resolves to an authenticated User, so the
        # old `is_authenticated` check let it through. When the spec sets
        # `allow_agent_approver: False`, a programmatic PAT must be rejected.
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        mock_janitor.return_value.get_approval.return_value = {
            "id": self.approval_id,
            "application_id": str(self.application.id),
            "approver_scope": {"allow_agent_approver": False},
        }
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="agent",
            user=self.user,
            secure_value=hash_key_value(raw_key),
            scopes=["agents:write"],
        )
        resp = self.client.post(
            self.url_decide,
            {"decision": "approve"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {raw_key}",
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        mock_janitor.return_value.decide_approval.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_personal_api_key_can_decide_when_agent_approver_allowed(self, mock_janitor) -> None:
        # The gate only applies when the spec disallows agent approvers.
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        mock_janitor.return_value.get_approval.return_value = {
            "id": self.approval_id,
            "application_id": str(self.application.id),
            "approver_scope": {"allow_agent_approver": True},
        }
        mock_janitor.return_value.decide_approval.return_value = {"ok": True, "state": "approving"}
        raw_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="agent",
            user=self.user,
            secure_value=hash_key_value(raw_key),
            scopes=["agents:write"],
        )
        resp = self.client.post(
            self.url_decide,
            {"decision": "approve"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {raw_key}",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_janitor.return_value.decide_approval.assert_called_once()
