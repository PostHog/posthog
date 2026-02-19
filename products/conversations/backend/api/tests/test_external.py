import uuid

from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Team

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Priority, Status


class TestExternalTicketAPI(BaseTest):
    def setUp(self):
        super().setUp()
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
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.team.api_token}"}

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

    # -- GET ticket -------------------------------------------------------

    def test_get_ticket_returns_all_fields(self):
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], str(self.ticket.id))
        self.assertEqual(data["ticket_number"], self.ticket.ticket_number)
        self.assertEqual(data["status"], "new")
        self.assertIsNone(data["priority"])
        self.assertEqual(data["channel_source"], "widget")
        self.assertEqual(data["distinct_id"], "user-ext-123")
        self.assertEqual(data["message_count"], 0)
        self.assertIsNone(data["last_message_at"])
        self.assertIsNone(data["last_message_text"])
        self.assertEqual(data["unread_team_count"], 0)
        self.assertEqual(data["unread_customer_count"], 0)
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)

    def test_get_ticket_not_found(self):
        url = f"/api/conversations/external/ticket/{uuid.uuid4()}"
        response = self.client.get(url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_ticket_cross_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        response = self.client.get(self.url, **self._auth_headers(token=other_team.api_token))
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
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        response = self.client.patch(
            self.url,
            {"status": "resolved"},
            content_type="application/json",
            **self._auth_headers(token=other_team.api_token),
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
