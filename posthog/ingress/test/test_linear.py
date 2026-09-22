import hmac
import json

from unittest.mock import Mock, patch

from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, SimpleTestCase

from posthog.ingress.contracts import DeliveryDispatch, DeliveryOwnershipAnswers
from posthog.ingress.linear.provider import build_linear_provider
from posthog.ingress.views import build_webhook_view

SECRET = "linear-webhook-secret"
BODY = json.dumps({"organizationId": "workspace-1"}).encode()


def _signature(secret: str) -> str:
    return hmac.digest(secret.encode(), BODY, "sha256").hex()


class TestLinearProvider(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.dispatcher = Mock()
        self.dispatcher.ownership_of.return_value = DeliveryOwnershipAnswers()
        self.dispatcher.dispatch.return_value = DeliveryDispatch()
        patcher = patch("posthog.ingress.views.get_dispatcher", return_value=self.dispatcher)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _request(self, signature: str) -> HttpRequest:
        return self.factory.post(
            "/webhooks/linear",
            data=BODY,
            content_type="application/json",
            headers={
                "Linear-Signature": signature,
                "Linear-Delivery": "a2af8b1a-9c68-4f95-9af0-797ca7f2f317",
                "Linear-Event": "Issue",
                "Linear-Timestamp": "0",
            },
        )

    def _response(self, secret: str, signature: str) -> HttpResponse:
        with patch("posthog.ingress.linear.provider.get_instance_setting", return_value=secret):
            return build_webhook_view(build_linear_provider())(self._request(signature))

    def test_a_signed_issue_reaches_dispatch_with_linear_context(self) -> None:
        response = self._response(SECRET, _signature(SECRET))

        self.assertEqual(response.status_code, 202)
        delivery = self.dispatcher.dispatch.call_args.args[0]
        self.assertEqual(delivery.event_type, "Issue")
        self.assertEqual(delivery.delivery_id, "a2af8b1a-9c68-4f95-9af0-797ca7f2f317")
        self.assertEqual(delivery.context, {"organization_id": "workspace-1"})

    def test_a_bad_signature_is_403(self) -> None:
        response = self._response(SECRET, "0" * 64)

        self.assertEqual(response.status_code, 403)
        self.dispatcher.dispatch.assert_not_called()

    def test_a_missing_secret_is_500(self) -> None:
        response = self._response("", _signature(SECRET))

        self.assertEqual(response.status_code, 500)
        self.dispatcher.dispatch.assert_not_called()
