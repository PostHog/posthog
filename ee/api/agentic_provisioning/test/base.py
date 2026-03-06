import json
import time

from posthog.test.base import APIBaseTest

from django.test import override_settings

from rest_framework.test import APIClient

from ee.api.agentic_provisioning.signature import compute_signature

HMAC_SECRET = "test_hmac_secret"


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class StripeProvisioningTestBase(APIBaseTest):
    HMAC_SECRET = HMAC_SECRET

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def _sign_body(self, body: bytes, timestamp: int | None = None) -> str:
        ts = timestamp if timestamp is not None else int(time.time())
        sig = compute_signature(self.HMAC_SECRET, ts, body)
        return f"t={ts},v1={sig}"

    def _post_signed(
        self, url: str, data: dict | bytes | None = None, content_type: str = "application/json", **kwargs
    ):
        body: bytes
        if content_type == "application/json":
            body = json.dumps(data or {}).encode()
        else:
            body = data if isinstance(data, bytes) else b""
        sig = self._sign_body(body)
        return self.client.post(
            url,
            data=body,
            content_type=content_type,
            HTTP_STRIPE_SIGNATURE=sig,
            HTTP_API_VERSION="0.1d",
            **kwargs,
        )

    def _get_signed(self, url: str, **kwargs):
        sig = self._sign_body(b"")
        return self.client.get(
            url,
            HTTP_STRIPE_SIGNATURE=sig,
            HTTP_API_VERSION="0.1d",
            **kwargs,
        )

    def _get_signed_with_bearer(self, url: str, token: str, **kwargs):
        sig = self._sign_body(b"")
        return self.client.get(
            url,
            HTTP_STRIPE_SIGNATURE=sig,
            HTTP_API_VERSION="0.1d",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            **kwargs,
        )

    def _post_signed_with_bearer(self, url: str, data: dict | None = None, token: str = "", **kwargs):
        body = json.dumps(data or {}).encode()
        sig = self._sign_body(body)
        return self.client.post(
            url,
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=sig,
            HTTP_API_VERSION="0.1d",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            **kwargs,
        )
