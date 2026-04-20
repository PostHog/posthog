import json
import time
from urllib.parse import urlencode

import pytest
from posthog.test.base import APIBaseTest

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework.test import APIClient

from ee.api.agentic_provisioning.signature import compute_signature
from ee.api.agentic_provisioning.views import AUTH_CODE_CACHE_PREFIX

HMAC_SECRET = "test_hmac_secret"
TEST_STRIPE_OAUTH_CLIENT_ID = "test_stripe_oauth_client_id"


def _generate_rsa_key() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


_RSA_KEY = _generate_rsa_key()


@pytest.mark.requires_secrets
@override_settings(
    STRIPE_APP_SECRET_KEY=HMAC_SECRET,
    STRIPE_POSTHOG_OAUTH_CLIENT_ID=TEST_STRIPE_OAUTH_CLIENT_ID,
    OIDC_RSA_PRIVATE_KEY=_RSA_KEY,
    OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": _RSA_KEY},
)
class StripeProvisioningTestBase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self._ensure_stripe_oauth_app()

    def _ensure_stripe_oauth_app(self):
        from posthog.models.oauth import OAuthApplication

        OAuthApplication.objects.get_or_create(
            client_id=TEST_STRIPE_OAUTH_CLIENT_ID,
            defaults={
                "name": "PostHog Stripe App",
                "client_secret": "",
                "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
                "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                "redirect_uris": "https://localhost",
                "algorithm": "RS256",
            },
        )

    def _sign_body(self, body: bytes, timestamp: int | None = None) -> str:
        ts = timestamp if timestamp is not None else int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)
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

    def _get_bearer_token(self) -> str:
        code = f"test_code_{id(self)}"
        cache.set(
            f"{AUTH_CODE_CACHE_PREFIX}{code}",
            {
                "user_id": self.user.id,
                "org_id": str(self.organization.id),
                "team_id": self.team.id,
                "stripe_account_id": "acct_123",
                "scopes": ["query:read"],
                "region": "US",
            },
            timeout=300,
        )
        body = urlencode({"grant_type": "authorization_code", "code": code}).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
            HTTP_API_VERSION="0.1d",
        )
        return res.json()["access_token"]
