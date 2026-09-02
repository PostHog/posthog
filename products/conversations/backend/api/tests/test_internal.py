import uuid
from datetime import timedelta

from posthog.test.base import BaseTest

from django.test import override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework import status
from rest_framework.test import APIClient

from posthog.jwt import PosthogJwtAudience
from posthog.models.utils import generate_random_token_secret
from posthog.scoped_service_jwt import ScopedServiceJwtPurpose

from products.conversations.backend.api.internal import CONVERSATIONS_TICKETS_PURPOSE
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status

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
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Status.NEW)

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

    def test_authenticated_get_increments_the_scoped_jwt_counter(self):
        labels = {"auth_method": "scoped_jwt", "http_method": "get"}
        before = REGISTRY.get_sample_value("posthog_conversations_ticket_action_auth_total", labels) or 0
        self.client.get(self.url, **self._headers())
        after = REGISTRY.get_sample_value("posthog_conversations_ticket_action_auth_total", labels)
        self.assertEqual(after, before + 1)
