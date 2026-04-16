import uuid

from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Team
from posthog.models.utils import generate_random_token_secret

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Priority, Status


class TestExternalTicketAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["conversations_enabled", "secret_api_token"])
        self.client = APIClient()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="user-ext-123",
            channel_source="widget",
            status=Status.NEW,
        )
        self.url = f"/api/conversations/external/ticket/{self.ticket.id}"

    def _auth_headers(self, token=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.team.secret_api_token}"}

    # -- Authentication ---------------------------------------------------

    def test_get_requires_auth(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_patch_requires_auth(self):
        response = self.client.patch(self.url, {"status": "resolved"}, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @parameterized.expand(
        [
            ("no_header", ""),
            ("bad_scheme", "Basic abc123"),
            ("empty_bearer", "Bearer "),
            ("wrong_token", "Bearer phc_wrong_token"),
        ]
    )
    def test_get_rejects_invalid_auth(self, _name, auth_value):
        headers = {"HTTP_AUTHORIZATION": auth_value} if auth_value else {}
        response = self.client.get(self.url, **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_public_api_token(self):
        response = self.client.get(self.url, **self._auth_headers(token=self.team.api_token))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_accepts_backup_token(self):
        backup_token = generate_random_token_secret()
        self.team.secret_api_token_backup = backup_token
        self.team.save(update_fields=["secret_api_token_backup"])
        response = self.client.get(self.url, **self._auth_headers(token=backup_token))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_rejects_when_conversations_disabled(self):
        self.team.conversations_enabled = False
        self.team.save(update_fields=["conversations_enabled"])
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -- GET ticket -------------------------------------------------------

    def test_get_ticket_returns_all_fields(self):
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], str(self.ticket.id))
        self.assertEqual(data["number"], self.ticket.ticket_number)
        self.assertEqual(data["status"], "new")
        self.assertIsNone(data["priority"])
        self.assertEqual(data["channel_source"], "widget")
        self.assertIsNone(data["channel_detail"])
        self.assertEqual(data["distinct_id"], "user-ext-123")
        self.assertEqual(data["message_count"], 0)
        self.assertIsNone(data["last_message_at"])
        self.assertIsNone(data["last_message_text"])
        self.assertEqual(data["unread_team_count"], 0)
        self.assertEqual(data["unread_customer_count"], 0)
        self.assertIsNone(data["sla"])
        self.assertIsNone(data["assignee"])
        self.assertIsNone(data["url"])
        self.assertIsNone(data["slack_channel_id"])
        self.assertIsNone(data["slack_thread_ts"])
        self.assertIsNone(data["slack_team_id"])
        self.assertIsNone(data["email_subject"])
        self.assertIsNone(data["email_from"])
        self.assertIsNone(data["email_to"])
        self.assertEqual(data["cc_participants"], [])
        self.assertEqual(data["tags"], [])
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)

    def test_get_ticket_not_found(self):
        url = f"/api/conversations/external/ticket/{uuid.uuid4()}"
        response = self.client.get(url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_ticket_cross_team_isolation(self):
        other_token = generate_random_token_secret()
        other_team = Team.objects.create(
            organization=self.organization, name="Other team", conversations_enabled=True, secret_api_token=other_token
        )
        response = self.client.get(self.url, **self._auth_headers(token=other_team.secret_api_token))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -- PATCH ticket -----------------------------------------------------

    @parameterized.expand([(s.value,) for s in Status])
    def test_patch_status_valid(self, new_status):
        response = self.client.patch(
            self.url, {"status": new_status}, content_type="application/json", **self._auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, new_status)

    @parameterized.expand([(p.value,) for p in Priority])
    def test_patch_priority_valid(self, new_priority):
        response = self.client.patch(
            self.url, {"priority": new_priority}, content_type="application/json", **self._auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.priority, new_priority)

    def test_patch_status_and_priority_together(self):
        response = self.client.patch(
            self.url,
            {"status": "pending", "priority": "high"},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "pending")
        self.assertEqual(self.ticket.priority, "high")

    def test_patch_invalid_status(self):
        response = self.client.patch(
            self.url, {"status": "nonexistent"}, content_type="application/json", **self._auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_invalid_priority(self):
        response = self.client.patch(
            self.url, {"priority": "critical"}, content_type="application/json", **self._auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_empty_body_is_noop(self):
        response = self.client.patch(self.url, {}, content_type="application/json", **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "new")

    def test_patch_ticket_not_found(self):
        url = f"/api/conversations/external/ticket/{uuid.uuid4()}"
        response = self.client.patch(
            url, {"status": "resolved"}, content_type="application/json", **self._auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_cross_team_isolation(self):
        other_token = generate_random_token_secret()
        other_team = Team.objects.create(
            organization=self.organization, name="Other team", conversations_enabled=True, secret_api_token=other_token
        )
        response = self.client.patch(
            self.url,
            {"status": "resolved"},
            content_type="application/json",
            **self._auth_headers(token=other_team.secret_api_token),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "new")

    def test_patch_ignores_unknown_fields(self):
        response = self.client.patch(
            self.url,
            {"status": "resolved", "hacked": True},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "resolved")

    # -- SLA updates --------------------------------------------------------

    def test_patch_sla_due_at_valid(self):
        response = self.client.patch(
            self.url,
            {"sla_due_at": "2026-03-15T14:30:00Z"},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.sla_due_at)
        self.assertEqual(self.ticket.sla_due_at.isoformat(), "2026-03-15T14:30:00+00:00")

    def test_patch_sla_due_at_null_clears_sla(self):
        from django.utils import timezone

        self.ticket.sla_due_at = timezone.now()
        self.ticket.save()

        response = self.client.patch(
            self.url,
            {"sla_due_at": None},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.sla_due_at)

    def test_patch_sla_due_at_invalid_format(self):
        response = self.client.patch(
            self.url,
            {"sla_due_at": "not-a-date"},
            content_type="application/json",
            **self._auth_headers(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_ticket_returns_sla_due_at(self):
        from django.utils import timezone

        self.ticket.sla_due_at = timezone.now()
        self.ticket.save()

        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.json()["sla"])

    # -- GET enriched fields -----------------------------------------------

    def test_get_ticket_returns_assignee(self):
        from products.conversations.backend.models import TicketAssignment

        TicketAssignment.objects.create(ticket=self.ticket, user=self.user)
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assignee = response.json()["assignee"]
        self.assertIsNotNone(assignee)
        self.assertEqual(assignee["type"], "user")
        self.assertEqual(assignee["id"], self.user.id)
        self.assertEqual(assignee["user"]["email"], self.user.email)

    def test_get_ticket_returns_role_assignee(self):
        from products.conversations.backend.models import TicketAssignment

        from ee.models.rbac.role import Role

        role = Role.objects.create(name="Support", organization=self.organization)
        TicketAssignment.objects.create(ticket=self.ticket, role=role)
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        assignee = response.json()["assignee"]
        self.assertEqual(assignee["type"], "role")
        self.assertEqual(assignee["id"], str(role.id))
        self.assertEqual(assignee["role"]["name"], "Support")
        self.assertIsNone(assignee["user"])

    def test_get_ticket_returns_url(self):
        self.ticket.session_context = {"current_url": "https://example.com/page"}
        self.ticket.save(update_fields=["session_context"])
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["url"], "https://example.com/page")

    def test_get_ticket_returns_slack_fields(self):
        self.ticket.slack_channel_id = "C1234567890"
        self.ticket.slack_thread_ts = "1234567890.123456"
        self.ticket.slack_team_id = "T0987654321"
        self.ticket.save(update_fields=["slack_channel_id", "slack_thread_ts", "slack_team_id"])
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["slack_channel_id"], "C1234567890")
        self.assertEqual(data["slack_thread_ts"], "1234567890.123456")
        self.assertEqual(data["slack_team_id"], "T0987654321")

    def test_get_ticket_returns_email_fields(self):
        from products.conversations.backend.models.team_conversations_email_config import EmailChannel

        channel = EmailChannel.objects.create(
            team=self.team, inbound_token="abc123", from_email="support@example.com", from_name="Support"
        )
        self.ticket.email_config = channel
        self.ticket.email_subject = "Need help with billing"
        self.ticket.email_from = "customer@example.com"
        self.ticket.cc_participants = ["cc1@example.com", "cc2@example.com"]
        self.ticket.save(update_fields=["email_config", "email_subject", "email_from", "cc_participants"])
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["email_subject"], "Need help with billing")
        self.assertEqual(data["email_from"], "customer@example.com")
        self.assertEqual(data["email_to"], "support@example.com")
        self.assertEqual(data["cc_participants"], ["cc1@example.com", "cc2@example.com"])

    def test_get_ticket_returns_tags(self):
        from posthog.models import Tag

        tag = Tag.objects.create(name="bug", team_id=self.team.id)
        self.ticket.tagged_items.create(tag=tag)
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["bug"])

    # -- URL validation ---------------------------------------------------

    def test_invalid_uuid_in_url_returns_404(self):
        response = self.client.get("/api/conversations/external/ticket/not-a-uuid", **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -- HTTP methods not allowed -----------------------------------------

    def test_post_not_allowed(self):
        response = self.client.post(self.url, {}, content_type="application/json", **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_not_allowed(self):
        response = self.client.delete(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_put_not_allowed(self):
        response = self.client.put(
            self.url, {"status": "resolved"}, content_type="application/json", **self._auth_headers()
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
