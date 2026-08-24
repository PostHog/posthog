import uuid

from posthog.test.base import BaseTest

from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.utils import generate_random_token_secret

from products.conversations.backend.api.internal import CONVERSATIONS_TICKETS_PURPOSE
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status


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

    def _headers(self, claims: dict | None = None) -> dict:
        if claims is None:
            claims = {"team_id": self.team.id, "ticket_id": str(self.ticket.id)}
        return {"HTTP_AUTHORIZATION": f"Bearer {CONVERSATIONS_TICKETS_PURPOSE.mint(claims)}"}

    def test_get_returns_ticket_for_minted_token(self):
        response = self.client.get(self.url, **self._headers())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], str(self.ticket.id))
        self.assertEqual(data["status"], "new")
        self.assertEqual(data["distinct_id"], "user-int-123")

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
        response = self.client.get(self.url, **make_headers(self))
        self.assertEqual(response.status_code, expected_status)

    def test_conversations_disabled_is_rejected(self):
        self.team.conversations_enabled = False
        self.team.save(update_fields=["conversations_enabled"])
        response = self.client.get(self.url, **self._headers())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_get_increments_the_scoped_jwt_counter(self):
        labels = {"auth_method": "scoped_jwt", "http_method": "get"}
        before = REGISTRY.get_sample_value("posthog_conversations_ticket_action_auth_total", labels) or 0
        self.client.get(self.url, **self._headers())
        after = REGISTRY.get_sample_value("posthog_conversations_ticket_action_auth_total", labels)
        self.assertEqual(after, before + 1)
