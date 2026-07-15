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

from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from ..logic.janitor_client import JanitorClientError
from ..models import AgentApplication


class TestApprovalEndpointsAuth(APIBaseTest):
    databases = {
        "default",
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
            "approver_scope": {"type": "agent"},
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
        AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="other-agent",
            name="Other Agent",
            description="",
        )
        # Approval belongs to a sibling application — the janitor's
        # `getForApplication` returns 404 when the URL's application_id
        # doesn't match the approval's owner. The view must propagate
        # that as 404; otherwise an admin on team A could decide
        # approvals on any agent in the same janitor DB just by mutating
        # the URL.
        mock_janitor.return_value.get_approval.side_effect = JanitorClientError(404, "not found")
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
    def test_principal_type_approval_is_not_decidable_here(self, mock_janitor) -> None:
        # `principal`-type approvals are the session owner's to clear at the
        # ingress decision API — the console (Django) only decides `agent`-type.
        # An admin hitting this endpoint for a principal row gets 404.
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        mock_janitor.return_value.get_approval.return_value = {
            "id": self.approval_id,
            "application_id": str(self.application.id),
            "approver_scope": {"type": "principal"},
        }
        resp = self.client.post(self.url_decide, {"decision": "approve"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        mock_janitor.return_value.decide_approval.assert_not_called()

    @parameterized.expand(
        [
            ("legacy_team_admins_decidable", {"approvers": ["team_admins"]}, True),
            ("legacy_session_principal_not_decidable", {"approvers": ["session_principal"]}, False),
            ("empty_scope_not_decidable", {}, False),
        ]
    )
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_decide_gate_resolves_legacy_scope_shapes(self, _name, scope, decidable, mock_janitor) -> None:
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        mock_janitor.return_value.get_approval.return_value = {
            "id": self.approval_id,
            "application_id": str(self.application.id),
            "approver_scope": scope,
        }
        mock_janitor.return_value.decide_approval.return_value = {"ok": True, "state": "approving"}
        resp = self.client.post(self.url_decide, {"decision": "approve"}, format="json")
        if decidable:
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            mock_janitor.return_value.decide_approval.assert_called_once()
        else:
            self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
            mock_janitor.return_value.decide_approval.assert_not_called()

    # A Personal API key resolves to an authenticated User but is not
    # `SessionAuthentication` — agent (owner) decisions require a human acting
    # interactively (session or first-party OAuth), so a PAT is always rejected.
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_personal_api_key_cannot_decide_agent_approval(self, mock_janitor) -> None:
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        mock_janitor.return_value.get_approval.return_value = {
            "id": self.approval_id,
            "application_id": str(self.application.id),
            "approver_scope": {"type": "agent"},
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

    def _make_oauth_token(self, *, scope: str, token: str, is_first_party: bool = False) -> OAuthAccessToken:
        oauth_application = OAuthApplication.objects.create(
            name=f"App {token}",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            skip_authorization=False,
            is_first_party=is_first_party,
            organization=self.organization,
            user=self.user,
        )
        return OAuthAccessToken.objects.create(
            user=self.user,
            application=oauth_application,
            token=token,
            expires=timezone.now() + timedelta(hours=1),
            scope=scope,
        )

    # An `agent` (owner) decision requires a human acting interactively. Only a
    # first-party PostHog OAuth app (e.g. PostHog Code, where a human approves
    # in-app) qualifies; a third-party OAuth app is rejected even with a broad
    # `*` scope — the gate keys off the app's staff-set `is_first_party` flag,
    # not the token scope.
    @parameterized.expand(
        [
            ("first_party_app", True, status.HTTP_200_OK, True),
            ("third_party_app", False, status.HTTP_404_NOT_FOUND, False),
        ]
    )
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_oauth_bearer_can_decide_agent_approval_only_when_first_party(
        self,
        label: str,
        is_first_party: bool,
        expected_status: int,
        decide_called: bool,
        mock_janitor,
    ) -> None:
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        mock_janitor.return_value.get_approval.return_value = {
            "id": self.approval_id,
            "application_id": str(self.application.id),
            "approver_scope": {"type": "agent"},
        }
        mock_janitor.return_value.decide_approval.return_value = {"ok": True, "state": "approving"}
        # `*` satisfies the viewset scope check for both; the first-party flag is
        # the only thing that differs.
        access_token = self._make_oauth_token(scope="*", token=f"pha_test_{label}", is_first_party=is_first_party)
        resp = self.client.post(
            self.url_decide,
            {"decision": "approve"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access_token.token}",
        )
        self.assertEqual(resp.status_code, expected_status)
        if decide_called:
            mock_janitor.return_value.decide_approval.assert_called_once()
        else:
            mock_janitor.return_value.decide_approval.assert_not_called()

    # `agent_approvals:write` does NOT satisfy the viewset-level
    # `scope_object = "agents"` check on its own — the token must also carry
    # `agents:write` (or `*`) to even reach the per-action gate. Without it
    # the request fails permission-check before the auth-class gate runs.
    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_oauth_bearer_decide_scope_alone_is_insufficient(self, mock_janitor) -> None:
        self._set_org_level(OrganizationMembership.Level.ADMIN)
        access_token = self._make_oauth_token(scope="agent_approvals:write", token="pha_test_decide_only")
        resp = self.client.post(
            self.url_decide,
            {"decision": "approve"},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access_token.token}",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        mock_janitor.return_value.decide_approval.assert_not_called()
