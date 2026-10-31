from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from ee.billing.billing_manager import BillingServiceResponseError


@override_settings(AI_GATEWAY_INTERNAL_TOKEN="gateway-token")
@patch("posthog.api.ai_gateway_reload.get_cached_instance_license")
@patch("ee.billing.billing_manager.BillingManager")
class TestAIGatewayReload(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.url = "/api/internal/ai_gateway/reload"

    def _headers(self, key: str | None = "low-balance-1") -> dict:
        headers = {"HTTP_AUTHORIZATION": "Bearer gateway-token"}
        if key:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        return headers

    def _reload(self, headers: dict | None = None, organization_id: str | None = None):
        return self.client.post(
            self.url,
            {"organization_id": organization_id or str(self.organization.id), "balance_usd": "4.104512"},
            format="json",
            **(headers if headers is not None else self._headers()),
        )

    def test_asks_billing_to_reload_the_organization(self, manager: MagicMock, license: MagicMock):
        reload = manager.return_value.reload_ai_balance
        reload.return_value = {"result": "charged", "amount_usd": "45.90"}

        response = self._reload()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"result": "charged", "amount_usd": "45.90"})
        manager.assert_called_once_with(license.return_value)
        reload.assert_called_once_with(self.organization, idempotency_key="low-balance-1", balance_usd="4.104512")

    def test_passes_back_only_the_reason_of_a_decline(self, manager: MagicMock, license: MagicMock):
        manager.return_value.reload_ai_balance.return_value = {
            "result": "declined",
            "reason": "card_declined",
            "detail": "billing's own words",
        }

        response = self._reload()

        self.assertEqual(response.json(), {"result": "declined", "reason": "card_declined"})

    def test_needs_an_idempotency_key(self, manager: MagicMock, license: MagicMock):
        response = self._reload(self._headers(key=None))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        manager.return_value.reload_ai_balance.assert_not_called()

    @parameterized.expand(
        [
            ("reload_running", 409, status.HTTP_409_CONFLICT),
            ("organization_does_not_buy", 403, status.HTTP_403_FORBIDDEN),
            ("charge_did_not_finish", 503, status.HTTP_503_SERVICE_UNAVAILABLE),
            ("billing_failed", 500, status.HTTP_503_SERVICE_UNAVAILABLE),
            ("billing_refused_the_request", 400, status.HTTP_503_SERVICE_UNAVAILABLE),
        ]
    )
    def test_answers_for_billing_with_its_own_words(
        self, manager: MagicMock, license: MagicMock, _name, billing_status, expected_status
    ):
        manager.return_value.reload_ai_balance.side_effect = BillingServiceResponseError(
            billing_status, {"detail": "billing's own words"}
        )

        response = self._reload()

        self.assertEqual(response.status_code, expected_status)
        self.assertNotIn("billing's own words", response.content.decode())

    def test_a_billing_timeout_asks_for_a_retry(self, manager: MagicMock, license: MagicMock):
        manager.return_value.reload_ai_balance.side_effect = requests.Timeout("read timed out")

        response = self._reload()

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("same Idempotency-Key", response.json()["detail"])

    def test_an_unknown_organization_is_not_found(self, manager: MagicMock, license: MagicMock):
        response = self._reload(organization_id="01234567-89ab-cdef-0123-456789abcdef")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        manager.return_value.reload_ai_balance.assert_not_called()

    @parameterized.expand(
        [
            ("another_token", "Bearer another-token", "gateway-token"),
            ("no_credentials", None, "gateway-token"),
            ("token_not_configured", "Bearer ", ""),
        ]
    )
    def test_rejected_credentials(self, manager: MagicMock, license: MagicMock, _name, authorization, configured_token):
        headers = {"HTTP_IDEMPOTENCY_KEY": "low-balance-1"}
        if authorization is not None:
            headers["HTTP_AUTHORIZATION"] = authorization

        with override_settings(AI_GATEWAY_INTERNAL_TOKEN=configured_token):
            response = self._reload(headers)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        manager.return_value.reload_ai_balance.assert_not_called()
