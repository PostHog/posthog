import hmac
import json
import hashlib

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.models.organization_integration import OrganizationIntegration

from ee.api.vercel.test.base import VercelTestBase

US_HOST = "us.posthog.com"
EU_HOST = "eu.posthog.com"


@override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="test_webhook_secret", ALLOWED_HOSTS=["*"])
class TestVercelWebhooks(VercelTestBase):
    def setUp(self):
        super().setUp()
        self.url = "/webhooks/vercel"
        self.secret = "test_webhook_secret"
        reset_consumer_registry()
        cache.clear()

    def tearDown(self):
        reset_consumer_registry()
        super().tearDown()

    def _sign_payload(self, payload: dict) -> str:
        body = json.dumps(payload).encode("utf-8")
        return hmac.new(
            self.secret.encode("utf-8"),
            body,
            hashlib.sha1,
        ).hexdigest()

    def _post_webhook(self, payload: dict, signature: str | None = None, host: str = US_HOST):
        headers = {} if signature is None else {"x-vercel-signature": signature}
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
            headers=headers,
            SERVER_NAME=host,
        )

    def _post_signed(self, payload: dict, host: str = US_HOST):
        return self._post_webhook(payload, signature=self._sign_payload(payload), host=host)

    def test_invalid_signature_returns_401(self):
        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": self.installation_id, "invoiceId": "mi_123"},
        }

        response = self._post_webhook(payload, signature="invalid_signature")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.content == b"Invalid signature"

    def test_missing_signature_returns_401(self):
        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": self.installation_id, "invoiceId": "mi_123"},
        }

        response = self._post_webhook(payload, signature=None)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @override_settings(VERCEL_CLIENT_INTEGRATION_SECRET="")
    def test_missing_secret_returns_500(self):
        payload = {"type": "marketplace.invoice.paid", "payload": {"installationId": self.installation_id}}

        response = self._post_webhook(payload, signature="anything")

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @parameterized.expand(
        [
            ("missing_config_id", {"type": "marketplace.invoice.paid", "payload": {"invoiceId": "mi_123"}}),
            (
                "unknown_config",
                {
                    "type": "marketplace.invoice.paid",
                    "payload": {"installationId": "icfg_unknown", "invoiceId": "mi_123"},
                },
            ),
            ("non_billing_event", {"type": "deployment.created", "payload": {"installationId": "icfg_1"}}),
            ("no_event_type", {"type": None, "payload": {"installationId": "icfg_1"}}),
            ("deauthorize_without_a_config_id", {"type": "integration-configuration.removed", "payload": {}}),
        ]
    )
    @patch("ee.api.vercel.webhook_events.BillingManager")
    def test_a_delivery_with_nothing_to_do_is_receipted(self, _name, payload, mock_billing_manager_class):
        response = self._post_signed(payload)

        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_billing_manager_class.assert_not_called()

    @patch("ee.api.vercel.webhook_events.VercelIntegration")
    def test_deauthorization_native_calls_delete_installation(self, mock_vercel_integration):
        assert OrganizationIntegration.objects.filter(integration_id=self.installation_id).exists()

        payload = {
            "type": "integration-configuration.removed",
            "payload": {"installationId": self.installation_id},
        }

        response = self._post_signed(payload)

        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_vercel_integration.delete_installation.assert_called_once_with(self.installation_id)

    @parameterized.expand(
        [
            ("installation_id", "installationId"),
            ("configuration_id", "configuration"),
        ]
    )
    def test_deauthorization_connectable_deletes_directly(self, _name, field):
        self.installation.config["type"] = "connectable"
        self.installation.save()
        event_payload = (
            {"installationId": self.installation_id}
            if field == "installationId"
            else {"configuration": {"id": self.installation_id}}
        )

        response = self._post_signed({"type": "integration-configuration.removed", "payload": event_payload})

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert not OrganizationIntegration.objects.filter(integration_id=self.installation_id).exists()

    @parameterized.expand(
        [
            ("the_region_vercel_delivers_to_forwards", US_HOST, True),
            ("the_region_that_receives_forwards_does_not", EU_HOST, False),
            ("anywhere_else_does_not", "testserver", False),
        ]
    )
    @patch("posthog.ingress.dispatch.forward.requests.request")
    def test_a_deauthorization_this_region_does_not_hold_is_forwarded(self, _name, host, expect_forward, mock_request):
        mock_request.return_value = MagicMock(ok=True, status_code=200)
        payload = {
            "type": "integration-configuration.removed",
            "payload": {"installationId": "icfg_unknown"},
        }

        response = self._post_signed(payload, host=host)

        assert response.status_code == status.HTTP_202_ACCEPTED
        if not expect_forward:
            mock_request.assert_not_called()
            return
        assert mock_request.call_args.kwargs["url"] == f"https://{EU_HOST}/webhooks/vercel"
        assert mock_request.call_args.kwargs["headers"]["x-vercel-signature"] == self._sign_payload(payload)

    @patch("posthog.ingress.dispatch.forward.requests.request")
    def test_a_billing_event_is_never_forwarded(self, mock_request):
        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": "icfg_unknown", "invoiceId": "mi_123"},
        }

        response = self._post_signed(payload)

        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_request.assert_not_called()

    @patch("ee.api.vercel.webhook_events.BillingManager")
    @patch("ee.api.vercel.webhook_events.License")
    def test_billing_event_forwarded_to_billing_service(self, mock_license_model, mock_billing_manager_class):
        mock_license_model.objects.first.return_value = MagicMock()
        mock_billing_manager = MagicMock()
        mock_billing_manager_class.return_value = mock_billing_manager

        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": self.installation_id, "invoiceId": "mi_123"},
        }

        response = self._post_signed(payload)

        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_billing_manager.handle_billing_provider_webhook.assert_called_once_with(
            event_type="marketplace.invoice.paid",
            event_data=payload["payload"],
            organization=self.organization,
            billing_provider="vercel",
        )

    @patch("ee.api.vercel.webhook_events.BillingManager")
    @patch("ee.api.vercel.webhook_events.License")
    def test_billing_error_returns_500(self, mock_license_model, mock_billing_manager_class):
        mock_license_model.objects.first.return_value = MagicMock()
        mock_billing_manager = MagicMock()
        mock_billing_manager_class.return_value = mock_billing_manager
        mock_billing_manager.handle_billing_provider_webhook.side_effect = Exception("Billing service error")

        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": self.installation_id, "invoiceId": "mi_123"},
        }

        response = self._post_signed(payload)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    @patch("ee.api.vercel.webhook_events.License")
    def test_no_license_returns_500(self, mock_license_model):
        mock_license_model.objects.first.return_value = None

        payload = {
            "type": "marketplace.invoice.paid",
            "payload": {"installationId": self.installation_id, "invoiceId": "mi_123"},
        }

        response = self._post_signed(payload)

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
