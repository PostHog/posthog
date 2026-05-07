import json
import base64
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken

from ee.api.agentic_provisioning import AUTH_CODE_CACHE_PREFIX
from ee.api.agentic_provisioning.test.base import HMAC_SECRET, ProvisioningTestBase
from ee.api.agentic_provisioning.views import PARTNER_RATE_LIMIT_DEFAULTS

PARTNER_CLIENT_ID = "partner_rate_limit_test"


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestPartnerRateLimits(ProvisioningTestBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        cache.clear()

        OAuthApplication.objects.filter(client_id=PARTNER_CLIENT_ID).delete()
        self.partner_app = OAuthApplication.objects.create(
            client_id=PARTNER_CLIENT_ID,
            name="Rate Limit Test Partner",
            client_secret="partner_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_first_party=True,
            provisioning_auth_method="pkce",
            provisioning_partner_type="test_partner",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _get_partner_bearer_token(self) -> str:
        code_verifier = secrets.token_urlsafe(32)
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        code = secrets.token_urlsafe(32)
        cache.set(
            f"{AUTH_CODE_CACHE_PREFIX}{code}",
            {
                "user_id": self.user.id,
                "org_id": str(self.organization.id),
                "team_id": self.team.id,
                "partner_id": str(self.partner_app.id),
                "scopes": ["query:read"],
                "region": "US",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
            timeout=300,
        )
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
            }
        ).encode()
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_API_VERSION="0.1d",
        )
        return res.json()["access_token"]

    # --- Unit tests for the rate limit helper ---

    @parameterized.expand(
        [
            ("account_requests",),
            ("token_exchanges",),
            ("resource_creates",),
        ]
    )
    def test_default_limit_applies_when_field_is_null(self, endpoint):
        from ee.api.agentic_provisioning.views import _enforce_partner_rate_limit

        assert getattr(self.partner_app, f"provisioning_rate_limit_{endpoint}") is None
        expected_limit = PARTNER_RATE_LIMIT_DEFAULTS[endpoint]

        for _ in range(expected_limit):
            assert _enforce_partner_rate_limit(self.partner_app, endpoint) is None

        response = _enforce_partner_rate_limit(self.partner_app, endpoint)
        assert response is not None
        assert response.status_code == 429

    def test_custom_override_respected(self):
        from ee.api.agentic_provisioning.views import _enforce_partner_rate_limit

        self.partner_app.provisioning_rate_limit_account_requests = 3
        self.partner_app.save(update_fields=["provisioning_rate_limit_account_requests"])

        for _ in range(3):
            assert _enforce_partner_rate_limit(self.partner_app, "account_requests") is None

        response = _enforce_partner_rate_limit(self.partner_app, "account_requests")
        assert response is not None
        assert response.status_code == 429
        assert "Retry-After" in response

    def test_zero_override_disables_limiting(self):
        from ee.api.agentic_provisioning.views import _enforce_partner_rate_limit

        self.partner_app.provisioning_rate_limit_account_requests = 0
        self.partner_app.save(update_fields=["provisioning_rate_limit_account_requests"])

        for _ in range(100):
            assert _enforce_partner_rate_limit(self.partner_app, "account_requests") is None

    def test_separate_buckets_per_endpoint(self):
        from ee.api.agentic_provisioning.views import _enforce_partner_rate_limit

        self.partner_app.provisioning_rate_limit_account_requests = 2
        self.partner_app.provisioning_rate_limit_resource_creates = 2
        self.partner_app.save(
            update_fields=[
                "provisioning_rate_limit_account_requests",
                "provisioning_rate_limit_resource_creates",
            ]
        )

        for _ in range(2):
            _enforce_partner_rate_limit(self.partner_app, "account_requests")

        assert _enforce_partner_rate_limit(self.partner_app, "account_requests") is not None
        assert _enforce_partner_rate_limit(self.partner_app, "resource_creates") is None

    def test_separate_buckets_per_partner(self):
        from ee.api.agentic_provisioning.views import _enforce_partner_rate_limit

        other_partner = OAuthApplication.objects.create(
            client_id="other_partner",
            name="Other Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://other.example.com/callback",
            algorithm="RS256",
            provisioning_auth_method="pkce",
            provisioning_partner_type="other",
            provisioning_active=True,
            provisioning_rate_limit_account_requests=2,
        )

        self.partner_app.provisioning_rate_limit_account_requests = 2
        self.partner_app.save(update_fields=["provisioning_rate_limit_account_requests"])

        for _ in range(2):
            _enforce_partner_rate_limit(self.partner_app, "account_requests")

        assert _enforce_partner_rate_limit(self.partner_app, "account_requests") is not None
        assert _enforce_partner_rate_limit(other_partner, "account_requests") is None

    # --- Integration: token exchange rate limiting ---

    def test_token_exchange_auth_code_rate_limited(self):
        self.partner_app.provisioning_rate_limit_token_exchanges = 1
        self.partner_app.save(update_fields=["provisioning_rate_limit_token_exchanges"])

        # First exchange succeeds
        self._get_partner_bearer_token()

        # Second exchange should be rate limited
        code_verifier = secrets.token_urlsafe(32)
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        code = secrets.token_urlsafe(32)
        cache.set(
            f"{AUTH_CODE_CACHE_PREFIX}{code}",
            {
                "user_id": self.user.id,
                "org_id": str(self.organization.id),
                "team_id": self.team.id,
                "partner_id": str(self.partner_app.id),
                "scopes": ["query:read"],
                "region": "US",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
            timeout=300,
        )
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
            }
        ).encode()
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 429

        # Auth code is consumed before the rate-limit check so a leaked code
        # can't be replayed to exhaust the bucket
        assert cache.get(f"{AUTH_CODE_CACHE_PREFIX}{code}") is None

    def test_token_exchange_refresh_rate_limited(self):
        self.partner_app.provisioning_rate_limit_token_exchanges = 1
        self.partner_app.save(update_fields=["provisioning_rate_limit_token_exchanges"])

        # Create access + refresh token for the partner
        access_token = OAuthAccessToken.objects.create(
            application=self.partner_app,
            token="test_access_token",
            user=self.user,
            expires=timezone.now() + timedelta(hours=1),
            scope="query:read",
            scoped_teams=[self.team.id],
        )
        OAuthRefreshToken.objects.create(
            application=self.partner_app,
            token="test_refresh_token_1",
            user=self.user,
            access_token=access_token,
            scoped_teams=[self.team.id],
        )

        # First refresh succeeds
        body = urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": "test_refresh_token_1",
            }
        ).encode()
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 200

        # Create a second refresh token
        new_access = OAuthAccessToken.objects.create(
            application=self.partner_app,
            token="test_access_token_2",
            user=self.user,
            expires=timezone.now() + timedelta(hours=1),
            scope="query:read",
            scoped_teams=[self.team.id],
        )
        OAuthRefreshToken.objects.create(
            application=self.partner_app,
            token="test_refresh_token_2",
            user=self.user,
            access_token=new_access,
            scoped_teams=[self.team.id],
        )

        body = urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": "test_refresh_token_2",
            }
        ).encode()
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 429

    # --- Integration: resource creation rate limiting ---

    def test_resource_create_rate_limited(self):
        self.partner_app.provisioning_rate_limit_resource_creates = 1
        self.partner_app.save(update_fields=["provisioning_rate_limit_resource_creates"])

        token = self._get_partner_bearer_token()

        # Reset the token_exchanges counter so it doesn't interfere
        cache.clear()
        # Re-set the resource_creates limit counter fresh
        # (cache.clear wiped it, but we need 1 request to fill it)

        res = self.client.post(
            "/api/agentic/provisioning/resources",
            data=json.dumps({"service_id": "analytics"}).encode(),
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert res.status_code == 200

        res = self.client.post(
            "/api/agentic/provisioning/resources",
            data=json.dumps({"service_id": "analytics"}).encode(),
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert res.status_code == 429
        assert res.json()["status"] == "error"
        assert res.json()["error"]["code"] == "rate_limited"

    # --- Stripe Projects (legacy HMAC) is not rate limited ---

    def test_stripe_projects_not_rate_limited(self):
        for _ in range(15):
            payload = {
                "id": f"acctreq_{secrets.token_hex(8)}",
                "email": f"user_{secrets.token_hex(4)}@example.com",
                "scopes": ["query:read"],
                "confirmation_secret": "cs_test",
                "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
                "orchestrator": {"type": "stripe", "stripe": {"account": "acct_123"}},
            }
            res = self._post_signed("/api/agentic/provisioning/account_requests", data=payload)
            assert res.status_code in (200, 201), f"Expected success, got {res.status_code}: {res.json()}"
