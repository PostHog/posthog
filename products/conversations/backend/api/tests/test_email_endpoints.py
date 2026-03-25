from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import Client


class TestEmailInboundRegionRouting(BaseTest):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def _post(self, data: dict[str, str]):
        return self.client.post("/api/conversations/v1/email/inbound", data=data)

    @patch("products.conversations.backend.api.email_events.proxy_to_secondary_region", return_value=True)
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    @patch("products.conversations.backend.api.email_events.is_primary_region", return_value=True)
    def test_proxies_to_secondary_when_token_not_found_on_primary(
        self, _mock_region: MagicMock, _mock_sig: MagicMock, mock_proxy: MagicMock
    ):
        response = self._post({"recipient": "team-deadbeef@mg.posthog.com"})

        assert response.status_code == 200
        mock_proxy.assert_called_once()

    @patch("products.conversations.backend.api.email_events.proxy_to_secondary_region", return_value=False)
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    @patch("products.conversations.backend.api.email_events.is_primary_region", return_value=True)
    def test_returns_502_when_proxy_fails(self, _mock_region: MagicMock, _mock_sig: MagicMock, mock_proxy: MagicMock):
        response = self._post({"recipient": "team-deadbeef@mg.posthog.com"})

        assert response.status_code == 502
        mock_proxy.assert_called_once()

    @patch("products.conversations.backend.api.email_events.proxy_to_secondary_region")
    @patch("products.conversations.backend.api.email_events.validate_webhook_signature", return_value=True)
    @patch("products.conversations.backend.api.email_events.is_primary_region", return_value=False)
    def test_returns_404_when_token_not_found_on_secondary(
        self, _mock_region: MagicMock, _mock_sig: MagicMock, mock_proxy: MagicMock
    ):
        response = self._post({"recipient": "team-deadbeef@mg.posthog.com"})

        assert response.status_code == 404
        mock_proxy.assert_not_called()
