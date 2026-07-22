import json
import time
from urllib.parse import urlencode

from posthog.test.base import APIBaseTest

from django.core.cache import cache
from django.test import override_settings

from rest_framework.test import APIClient

from posthog.models.oauth import OAuthApplication

from ee.partners.stripe.api.provisioning import AUTH_CODE_CACHE_PREFIX
from ee.partners.stripe.api.provisioning.signature import compute_signature

HMAC_SECRET = "test_hmac_secret"
TEST_STRIPE_OAUTH_CLIENT_ID = "test_stripe_oauth_client_id"

BASE_PATH = "/api/partners/stripe"


@override_settings(
    STRIPE_SIGNING_SECRET=HMAC_SECRET,
    STRIPE_POSTHOG_OAUTH_CLIENT_ID=TEST_STRIPE_OAUTH_CLIENT_ID,
)
class StripeProvisioningTestBase(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self._ensure_stripe_oauth_app()

    def _ensure_stripe_oauth_app(self):
        # No provisioning_* flags: this namespace authorizes by identity
        # (client_id) alone and does not read the app's provisioning config.
        self.stripe_app, _ = OAuthApplication.objects.get_or_create(
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

    def _create_other_partner_app(self, **overrides):
        defaults = {
            "client_id": "other-partner",
            "name": "Other Partner",
            "client_secret": "",
            "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": "https://localhost",
            "algorithm": "RS256",
        }
        defaults.update(overrides)
        return OAuthApplication.objects.create(**defaults)

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
        elif isinstance(data, bytes):
            body = data
        elif data is not None:
            body = urlencode(data).encode()
        else:
            body = b""
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

    def _seed_auth_code(self, code: str, **overrides):
        value = {
            "user_id": self.user.id,
            "org_id": str(self.organization.id),
            "team_id": self.team.id,
            "stripe_account_id": "acct_123",
            "scopes": ["query:read"],
            "region": "US",
            **overrides,
        }
        cache.set(f"{AUTH_CODE_CACHE_PREFIX}{code}", value, timeout=300)
        return value

    def _request_bearer_token(self):
        code = f"test_code_{id(self)}"
        self._seed_auth_code(code)
        body = urlencode({"grant_type": "authorization_code", "code": code}).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)
        return self.client.post(
            f"{BASE_PATH}/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            headers={"stripe-signature": f"t={ts},v1={sig}", "api-version": "0.1d"},
        )

    def _get_bearer_token(self) -> str:
        return self._request_bearer_token().json()["access_token"]
