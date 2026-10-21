import uuid
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework import status
from rest_framework.test import APIClient
from slack_sdk.errors import SlackApiError

from posthog.jwt import PosthogJwtAudience
from posthog.models import Comment, OrganizationMembership, Team, User
from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration
from posthog.models.utils import generate_random_token_secret
from posthog.redis import get_client
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose
from posthog.test.authentication_checks import covers_authentication

from products.access_control.backend.models.role import Role
from products.conversations.backend.api.internal import (
    CONVERSATIONS_TICKETS_PURPOSE,
    ConversationsTicketJWTAuthentication,
)
from products.conversations.backend.models import Ticket, TicketAssignment
from products.conversations.backend.models.constants import WORKFLOW_AUTHOR_NAME, WORKFLOW_AUTHOR_TYPE, Status

# Signed with this route's key but carrying another surface's audience — a token minted for a
# different purpose must never authenticate here even when the signing key checks out.
OTHER_AUDIENCE_PURPOSE = ScopedServiceJwtPurpose(
    audience=PosthogJwtAudience.RECORDING_API,
    settings_name="CONVERSATIONS_TICKETS_JWT_SECRETS",
)


class TestInternalTicketAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["conversations_enabled", "secret_api_token"])
        self.client = APIClient()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user-int-123",
            channel_source="widget",
            status=Status.NEW,
        )
        self.url = f"/api/projects/{self.team.id}/internal/conversations/tickets/{self.ticket.id}"

    def _claims(self) -> dict:
        return {"team_id": self.team.id, "ticket_id": str(self.ticket.id)}

    def _headers(self, claims: dict | None = None) -> dict:
        return self._bearer(CONVERSATIONS_TICKETS_PURPOSE.mint(claims if claims is not None else self._claims()))

    @staticmethod
    def _bearer(token: str) -> dict:
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    @covers_authentication(ConversationsTicketJWTAuthentication)
    def test_get_returns_ticket_for_minted_token(self):
        response = self.client.get(self.url, **self._headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], str(self.ticket.id))
        self.assertEqual(data["status"], "new")
        self.assertEqual(data["distinct_id"], "user-int-123")

    def test_get_returns_first_customer_message_text_when_opted_in(self):
        # The field is shared with the external route but gated behind a query param, so confirm
        # the JWT route reads that param and returns the preview through the same handler.
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="How do I export my data?",
            item_context={"author_type": "customer"},
        )
        response = self.client.get(self.url, {"include_first_customer_message_text": "true"}, **self._headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["first_customer_message_text"], "How do I export my data?")

    def test_post_sends_a_public_message(self):
        response = self.client.post(
            self.url,
            {"message": "  We are on it.  ", "idempotency_key": "run-1:send:0"},
            content_type="application/json",
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body["is_private"], False)
        comment = Comment.objects.get(id=body["id"], team_id=self.team.id)
        self.assertEqual(comment.content, "We are on it.")
        self.assertEqual(comment.item_id, str(self.ticket.id))
        self.assertIsNone(comment.created_by_id)
        item_context = comment.item_context
        assert item_context is not None
        self.assertEqual(item_context["author_type"], WORKFLOW_AUTHOR_TYPE)
        self.assertEqual(item_context["author_name"], WORKFLOW_AUTHOR_NAME)
        self.assertFalse(item_context["is_private"])

    def test_post_private_note(self):
        response = self.client.post(
            self.url,
            {"message": "Internal only", "is_private": True, "idempotency_key": "run-1:note:0"},
            content_type="application/json",
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.json()["is_private"])
        comment = Comment.objects.get(id=response.json()["id"], team_id=self.team.id)
        item_context = comment.item_context
        assert item_context is not None
        self.assertTrue(item_context["is_private"])
        self.assertEqual(item_context["author_type"], WORKFLOW_AUTHOR_TYPE)

    def test_post_deduplicates_by_workflow_step_execution(self):
        payload = {"message": "We are on it.", "is_private": False, "idempotency_key": "run-1:send:0"}
        first = self.client.post(self.url, payload, content_type="application/json", **self._headers())
        second = self.client.post(
            self.url,
            {**payload, "message": "Changed after retry"},
            content_type="application/json",
            **self._headers(),
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.json()["id"], first.json()["id"])
        self.assertEqual(Comment.objects.filter(team_id=self.team.id, item_id=str(self.ticket.id)).count(), 1)

        next_run = self.client.post(
            self.url,
            {"message": "We are on it.", "is_private": False, "idempotency_key": "run-2:send:0"},
            content_type="application/json",
            **self._headers(),
        )
        self.assertEqual(next_run.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(next_run.json()["id"], first.json()["id"])
        self.assertEqual(Comment.objects.filter(team_id=self.team.id, item_id=str(self.ticket.id)).count(), 2)

    def test_post_rejects_blank_message(self):
        response = self.client.post(
            self.url,
            {"message": "   ", "idempotency_key": "run-1:send:0"},
            content_type="application/json",
            **self._headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Comment.objects.filter(team_id=self.team.id, item_id=str(self.ticket.id)).exists())

    def test_post_unknown_ticket_creates_nothing(self):
        missing = uuid.uuid4()
        url = f"/api/projects/{self.team.id}/internal/conversations/tickets/{missing}"
        headers = self._headers({"team_id": self.team.id, "ticket_id": str(missing)})
        response = self.client.post(
            url,
            {"message": "hello", "idempotency_key": "run-1:send:0"},
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(Comment.objects.filter(team_id=self.team.id, item_id=str(missing)).exists())

    def test_patch_updates_ticket(self):
        response = self.client.patch(
            self.url, {"status": "resolved"}, content_type="application/json", **self._headers()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "resolved")

    @parameterized.expand(
        [
            (
                "token_for_another_team",
                lambda self: self._headers({"team_id": self.team.id + 1, "ticket_id": str(self.ticket.id)}),
                status.HTTP_401_UNAUTHORIZED,
            ),
            (
                "legacy_secret_api_token",
                lambda self: {"HTTP_AUTHORIZATION": f"Bearer {self.team.secret_api_token}"},
                status.HTTP_401_UNAUTHORIZED,
            ),
            (
                "expired_token",
                lambda self: self._bearer(
                    CONVERSATIONS_TICKETS_PURPOSE.mint(self._claims(), ttl=timedelta(minutes=-1))
                ),
                status.HTTP_401_UNAUTHORIZED,
            ),
            (
                "token_for_another_purpose",
                lambda self: self._bearer(OTHER_AUDIENCE_PURPOSE.mint(self._claims())),
                status.HTTP_401_UNAUTHORIZED,
            ),
            (
                "missing_ticket_claim",
                lambda self: self._headers({"team_id": self.team.id}),
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "token_for_another_ticket",
                lambda self: self._headers({"team_id": self.team.id, "ticket_id": str(uuid.uuid4())}),
                status.HTTP_403_FORBIDDEN,
            ),
            ("no_credentials", lambda self: {}, status.HTTP_401_UNAUTHORIZED),
        ]
    )
    def test_rejected_credentials(self, _name, make_headers, expected_status):
        headers = make_headers(self)
        get_response = self.client.get(self.url, **headers)
        self.assertEqual(get_response.status_code, expected_status)
        patch_response = self.client.patch(self.url, {"status": "resolved"}, content_type="application/json", **headers)
        self.assertEqual(patch_response.status_code, expected_status)
        post_response = self.client.post(
            self.url, {"message": "should not land"}, content_type="application/json", **headers
        )
        self.assertEqual(post_response.status_code, expected_status)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.NEW)
        self.assertFalse(Comment.objects.filter(team_id=self.team.id, item_id=str(self.ticket.id)).exists())

    def test_unprovisioned_secret_rejects_even_a_well_formed_token(self):
        headers = self._headers()
        with override_settings(CONVERSATIONS_TICKETS_JWT_SECRETS=[]):
            response = self.client.get(self.url, **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_conversations_disabled_is_rejected(self):
        self.team.conversations_enabled = False
        self.team.save(update_fields=["conversations_enabled"])
        response = self.client.get(self.url, **self._headers())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        post_response = self.client.post(
            self.url, {"message": "should not land"}, content_type="application/json", **self._headers()
        )
        self.assertEqual(post_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Comment.objects.filter(team_id=self.team.id, item_id=str(self.ticket.id)).exists())

    def test_authenticated_get_increments_the_scoped_jwt_counter(self):
        labels = {"auth_method": "scoped_jwt", "http_method": "get"}
        before = REGISTRY.get_sample_value("posthog_conversations_ticket_action_auth_total", labels) or 0
        self.client.get(self.url, **self._headers())
        after = REGISTRY.get_sample_value("posthog_conversations_ticket_action_auth_total", labels)
        self.assertEqual(after, before + 1)


SLACK_WORKSPACE_ID = "T123"


def _slack_member(member_id: str, **overrides: object) -> dict:
    return {"user": {"id": member_id, "team_id": SLACK_WORKSPACE_ID, **overrides}}


def _slack_error(code: str) -> SlackApiError:
    return SlackApiError(code, MagicMock(get=lambda key, default=None: code))


class TestInternalTicketAssigneeSlackDm(BaseTest):
    def setUp(self):
        super().setUp()
        get_client().flushall()
        self.team.conversations_enabled = True
        self.team.save(update_fields=["conversations_enabled"])
        self.client = APIClient()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user-int-123",
            channel_source="widget",
            status=Status.NEW,
        )
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id=SLACK_WORKSPACE_ID,
            sensitive_config={"access_token": "xoxb-test"},
        )
        self.assignee = User.objects.create_and_join(self.organization, "ada@example.com", None, first_name="Ada")
        self.url = f"/api/projects/{self.team.id}/internal/conversations/tickets/{self.ticket.id}/assignee_slack_dm"

        self.slack_client = MagicMock()
        self.slack_client.users_info.side_effect = lambda user: _slack_member(user)
        self.slack_client.users_lookupByEmail.return_value = {"ok": True, "user": {"id": "U-by-email"}}
        client_patch = patch("posthog.models.integration.slack.WebClient", return_value=self.slack_client)
        client_patch.start()
        self.addCleanup(client_patch.stop)

    def _post(
        self, idempotency_key: str = "run-1:dm:0", integration_id: int | None = None, text: str = "Ticket needs you"
    ):
        token = CONVERSATIONS_TICKETS_PURPOSE.mint({"team_id": self.team.id, "ticket_id": str(self.ticket.id)})
        return self.client.post(
            self.url,
            {
                "integration_id": integration_id or self.integration.id,
                "text": text,
                "idempotency_key": idempotency_key,
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def _assign(self, user: User) -> None:
        TicketAssignment.objects.create(ticket=self.ticket, user=user)

    def _link_slack(self, slack_user_id: str, workspace_id: str = SLACK_WORKSPACE_ID) -> None:
        UserIntegration.objects.create(
            user=self.assignee,
            kind=UserIntegration.IntegrationKind.SLACK,
            integration_id=slack_user_id,
            config={"slack_team_id": workspace_id},
        )

    def _assign_role(self) -> None:
        TicketAssignment.objects.create(
            ticket=self.ticket, role=Role.objects.create(name="Support", organization=self.organization)
        )

    def _remove_from_organization(self) -> None:
        self._assign(self.assignee)
        OrganizationMembership.objects.filter(user=self.assignee).delete()

    def _deactivate(self) -> None:
        self._assign(self.assignee)
        self.assignee.is_active = False
        self.assignee.save(update_fields=["is_active"])

    def _no_slack_member(self) -> None:
        self._assign(self.assignee)
        self.slack_client.users_lookupByEmail.side_effect = _slack_error("users_not_found")

    def _slack_member_overrides(self, **overrides: object) -> None:
        self._assign(self.assignee)
        self.slack_client.users_info.side_effect = lambda user: _slack_member(user, **overrides)

    @parameterized.expand(
        [
            ("linked_account_wins_over_email", SLACK_WORKSPACE_ID, "U-linked"),
            ("link_to_another_workspace_falls_back_to_email", "T-other", "U-by-email"),
        ]
    )
    def test_sends_dm_to_the_assignee(self, _name, linked_workspace, expected_member):
        self._assign(self.assignee)
        self._link_slack("U-linked", workspace_id=linked_workspace)

        response = self._post(text="From <https://evil.example|Support> <!channel>")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"outcome": "sent", "slack_user_id": expected_member})
        sent = self.slack_client.chat_postMessage.call_args.kwargs
        self.assertEqual(sent["channel"], expected_member)
        self.assertEqual(sent["text"], "From &lt;https://evil.example|Support&gt; &lt;!channel&gt;")
        self.assertTrue(
            sent["blocks"][1]["elements"][0]["url"].endswith(f"/support/tickets/{self.ticket.ticket_number}")
        )

    @covers_authentication(ConversationsTicketJWTAuthentication)
    def test_unassigned_ticket_sends_nothing(self):
        response = self._post()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"outcome": "unassigned", "slack_user_id": None})
        self.slack_client.chat_postMessage.assert_not_called()

    def test_retry_of_the_same_step_does_not_send_twice(self):
        self._assign(self.assignee)

        first = self._post()
        retry = self._post()
        next_step = self._post(idempotency_key="run-1:dm:1")

        self.assertEqual([first.status_code, retry.status_code, next_step.status_code], [200, 200, 200])
        self.assertEqual(retry.json(), {"outcome": "sent", "slack_user_id": "U-by-email"})
        self.assertEqual(self.slack_client.chat_postMessage.call_count, 2)

    @parameterized.expand(
        [
            ("slack_refused_so_retry_sends", _slack_error("channel_not_found"), "channel_not_found", 2),
            ("outcome_unknown_so_retry_replays", TimeoutError("read timed out"), "did not confirm", 1),
        ]
    )
    def test_failed_send_then_retry(self, _name, send_error, expected_error, expected_sends):
        self._assign(self.assignee)
        self.slack_client.chat_postMessage.side_effect = [send_error, {"ok": True}]

        failed = self._post()
        retried = self._post()

        self.assertEqual(failed.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(expected_error, failed.json()["error"])
        self.assertEqual(retried.status_code, status.HTTP_200_OK)
        self.assertEqual(self.slack_client.chat_postMessage.call_count, expected_sends)

    @parameterized.expand(
        [
            ("role_assignee", _assign_role, "assigned to Support"),
            ("assignee_left_organization", _remove_from_organization, "no longer has access"),
            ("assignee_deactivated", _deactivate, "no longer has access"),
            ("no_slack_member_for_email", _no_slack_member, "could not find Ada"),
            (
                "email_matches_slack_connect_member",
                lambda t: t._slack_member_overrides(team_id="T-elsewhere"),
                "could not find Ada",
            ),
            ("email_matches_guest", lambda t: t._slack_member_overrides(is_restricted=True), "could not find Ada"),
        ]
    )
    def test_undeliverable_assignee_fails_the_step(self, _name, arrange, expected_error):
        arrange(self)

        response = self._post()

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(expected_error, response.json()["error"])
        self.slack_client.chat_postMessage.assert_not_called()

    def test_slack_integration_from_another_team_is_refused(self):
        self._assign(self.assignee)
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        foreign = Integration.objects.create(
            team=other_team, kind="slack", integration_id="T999", sensitive_config={"access_token": "xoxb-other"}
        )

        response = self._post(integration_id=foreign.id)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.slack_client.chat_postMessage.assert_not_called()
