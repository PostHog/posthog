import hmac
import json
import hashlib

from unittest.mock import MagicMock, patch

from django.test import override_settings

from rest_framework import status

from ee.api.vercel.test.base import VercelTestBase


class TestVercelWebhooks(VercelTestBase):
    def setUp(self):
        super().setUp()
        self.url = "/webhooks/vercel"
        self.secret = "test_webhook_secret"

    def _sign_payload(self, payload: dict) -> str:
        body = json.dumps(payload).encode("utf-8")
        return hmac.new(
            self.secret.encode("utf-8"),
            body,
            hashlib.sha1,
        ).hexdigest()

    def _post_webhook(self, payload: dict, signature: str | None = None):
        if signature is not None:
            return self.client.post(
                self.url,
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_X_VERCEL_SIGNATURE=signature,
            )
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )

    @override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="test_webhook_secret")
    def test_invalid_signature_returns_401(self):
        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": self.installation_id, "invoiceId": "mi_123"},
        }

        response = self._post_webhook(payload, signature="invalid_signature")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["error"] == "Invalid signature"

    @override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="test_webhook_secret")
    def test_missing_signature_returns_401(self):
        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": self.installation_id, "invoiceId": "mi_123"},
        }

        response = self._post_webhook(payload, signature=None)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="test_webhook_secret")
    def test_missing_config_id_returns_400(self):
        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"invoiceId": "mi_123"},  # Missing installationId
        }
        signature = self._sign_payload(payload)

        response = self._post_webhook(payload, signature=signature)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "configurationId" in response.json()["error"]  # Error message still says configurationId

    @override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="test_webhook_secret")
    def test_unknown_config_returns_404(self):
        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": "icfg_unknown", "invoiceId": "mi_123"},
        }
        signature = self._sign_payload(payload)

        response = self._post_webhook(payload, signature=signature)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Unknown configuration" in response.json()["error"]

    @override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="test_webhook_secret")
    def test_non_billing_events_ignored(self):
        # Non-invoice marketplace events should be ignored
        for event_type in [
            "integration.configuration-removed",
            "deployment.created",
            "marketplace.member.created",  # Other marketplace events that aren't invoices
            None,
        ]:
            payload = {
                "type": event_type,
                "payload": {"installationId": self.installation_id},
            }
            signature = self._sign_payload(payload)

            response = self._post_webhook(payload, signature=signature)

            assert response.status_code == status.HTTP_200_OK
            assert response.json()["status"] == "ignored"

    @override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="test_webhook_secret")
    @patch("ee.api.vercel.vercel_webhooks.BillingManager")
    @patch("ee.api.vercel.vercel_webhooks.License")
    def test_billing_event_forwarded_to_billing_service(self, mock_license_model, mock_billing_manager_class):
        mock_license = MagicMock()
        mock_license_model.objects.first.return_value = mock_license

        mock_billing_manager = MagicMock()
        mock_billing_manager_class.return_value = mock_billing_manager

        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": self.installation_id, "invoiceId": "mi_123"},
        }
        signature = self._sign_payload(payload)

        response = self._post_webhook(payload, signature=signature)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "ok"

        mock_billing_manager.handle_billing_provider_webhook.assert_called_once_with(
            event_type="marketplace.invoice.paid",
            event_data=payload["payload"],
            organization=self.organization,
            billing_provider="vercel",
        )

    @override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="test_webhook_secret")
    @patch("ee.api.vercel.vercel_webhooks.BillingManager")
    @patch("ee.api.vercel.vercel_webhooks.License")
    def test_billing_error_returns_500(self, mock_license_model, mock_billing_manager_class):
        mock_license = MagicMock()
        mock_license_model.objects.first.return_value = mock_license

        mock_billing_manager = MagicMock()
        mock_billing_manager_class.return_value = mock_billing_manager
        mock_billing_manager.handle_billing_provider_webhook.side_effect = Exception("Billing service error")

        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": self.installation_id, "invoiceId": "mi_123"},
        }
        signature = self._sign_payload(payload)

        response = self._post_webhook(payload, signature=signature)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Processing failed" in response.json()["error"]

    @override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="test_webhook_secret")
    @patch("ee.api.vercel.vercel_webhooks.License")
    def test_no_license_returns_500(self, mock_license_model):
        mock_license_model.objects.first.return_value = None

        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": self.installation_id, "invoiceId": "mi_123"},
        }
        signature = self._sign_payload(payload)

        response = self._post_webhook(payload, signature=signature)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Processing failed" in response.json()["error"]
