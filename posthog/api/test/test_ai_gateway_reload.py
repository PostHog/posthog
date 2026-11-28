import json
from typing import Any

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
        self.url = "/api/internal/ai_gateway/reloads"

    def _envelope(self, **body: object) -> dict:
        signed = {
            "type": "ai_reload_requested",
            "version": 1,
            "audience": "billing",
            "organization_id": str(self.organization.id),
            "reload_key": "low-balance-1",
            "balance_micros": 4104512,
            **body,
        }
        return {
            # The trailing newline that Go's json.Encoder writes is part of what the gateway signed.
            "body": json.dumps(signed) + "\n",
            "signed_at": "2026-11-23T18:04:05Z",
            "key_id": "ai-gateway-us-1",
            "signature": "5f0c1e",
        }

    def _reload(self, envelope: dict | None = None, authorization: str | None = "Bearer gateway-token"):
        headers: dict[str, Any] = {"HTTP_AUTHORIZATION": authorization} if authorization is not None else {}
        return self.client.post(self.url, envelope or self._envelope(), format="json", **headers)

    def test_passes_the_envelope_unchanged_to_billing(self, manager: MagicMock, license: MagicMock):
        reload = manager.return_value.reload_ai_balance
        reload.return_value = {"result": "accepted"}
        envelope = self._envelope()

        response = self._reload(envelope)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.json(), {"result": "accepted"})
        manager.assert_called_once_with(license.return_value)
        reload.assert_called_once_with(self.organization, envelope)

    def test_passes_back_only_the_result(self, manager: MagicMock, license: MagicMock):
        manager.return_value.reload_ai_balance.return_value = {"result": "accepted", "detail": "billing's own words"}

        response = self._reload()

        self.assertEqual(response.json(), {"result": "accepted"})

    @parameterized.expand(
        [
            ("another_message_type", {"type": "ai_withdrawal_answered"}, {}),
            ("signature_not_a_string", {}, {"signature": 5}),
        ]
    )
    def test_an_envelope_it_cannot_route_is_a_bad_request(
        self, manager: MagicMock, license: MagicMock, _name, body, fields
    ):
        response = self._reload({**self._envelope(**body), **fields})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        manager.return_value.reload_ai_balance.assert_not_called()

    @parameterized.expand(
        [
            ("organization_does_not_buy", 403, status.HTTP_403_FORBIDDEN),
            ("charge_did_not_finish", 503, status.HTTP_503_SERVICE_UNAVAILABLE),
            ("billing_failed", 500, status.HTTP_503_SERVICE_UNAVAILABLE),
            ("billing_refused_the_request", 400, status.HTTP_503_SERVICE_UNAVAILABLE),
            ("billing_rejected_the_signature", 401, status.HTTP_503_SERVICE_UNAVAILABLE),
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
        self.assertIn("same reload key", response.json()["detail"])

    def test_an_unknown_organization_is_not_found(self, manager: MagicMock, license: MagicMock):
        response = self._reload(self._envelope(organization_id="01234567-89ab-4def-8123-456789abcdef"))

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
        with override_settings(AI_GATEWAY_INTERNAL_TOKEN=configured_token):
            response = self._reload(authorization=authorization)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        manager.return_value.reload_ai_balance.assert_not_called()
