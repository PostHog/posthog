from decimal import Decimal

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models import ActivityLog, PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status


class TestGenerateMerchCode(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="merch-session",
            distinct_id="user-1",
            status=Status.NEW,
        )

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/generate_merch_code/"

    def _make_staff(self) -> None:
        self.user.is_staff = True
        self.user.save()

    def test_non_staff_forbidden(self) -> None:
        response = self.client.post(self._url(), {"value_usd": "30"}, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("products.conversations.backend.api.tickets.create_merch_code")
    def test_personal_api_key_cannot_mint_even_for_staff(self, mock_create) -> None:
        # A staff member's PAT (any scope) must not reach this money-minting action: it is restricted
        # to SessionAuthentication, so a token-only request never authenticates. Drop the test
        # client's session so only the Bearer token is presented.
        self._make_staff()
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="merch test", user=self.user, secure_value=hash_key_value(key_value), scopes=["*"]
        )
        self.client.logout()
        response = self.client.post(
            self._url(), {"value_usd": "30"}, format="json", HTTP_AUTHORIZATION=f"Bearer {key_value}"
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_create.assert_not_called()

    @patch("products.conversations.backend.api.tickets.create_merch_code")
    def test_value_over_cap_rejected_before_minting(self, mock_create) -> None:
        self._make_staff()
        with self.settings(SHOPIFY_MERCH_MAX_VALUE_USD=150):
            response = self.client.post(self._url(), {"value_usd": "500"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_create.assert_not_called()

    def test_not_configured_returns_503(self) -> None:
        self._make_staff()
        with self.settings(SHOPIFY_MERCH_ACCESS_TOKEN="", SHOPIFY_MERCH_HASH_KEY=""):
            response = self.client.post(self._url(), {"value_usd": "30"}, format="json")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    @patch("products.conversations.backend.api.tickets.create_merch_code")
    def test_success_returns_code_and_audits(self, mock_create) -> None:
        self._make_staff()
        mock_create.return_value = {
            "code": "abc123def456",
            "value_usd": Decimal("50"),
            "usage_limit": 1,
            "discount_url": "https://shop.posthog.com/discount/abc123def456",
            "admin_url": "https://admin.shopify.com/store/posthog/discounts/987",
        }
        response = self.client.post(self._url(), {"value_usd": "50"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["code"] == "abc123def456"
        assert body["discount_url"].endswith("/abc123def456")
        assert mock_create.call_args.kwargs["context"] == f"ticket-{self.ticket.ticket_number}"
        # Codes are always single-use regardless of any client-supplied value.
        assert mock_create.call_args.kwargs["usage_limit"] == 1

        log = ActivityLog.objects.filter(
            scope="Ticket", item_id=str(self.ticket.id), activity="generated_merch_code"
        ).first()
        assert log is not None
        # The activity log is readable by non-staff members, so it must reference the code (last 4)
        # without exposing the full redeemable value.
        serialized = str(log.detail)
        assert "abc123def456" not in serialized
        assert "f456" in serialized
