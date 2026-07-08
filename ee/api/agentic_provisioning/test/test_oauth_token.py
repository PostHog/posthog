import time
from datetime import timedelta
from urllib.parse import urlencode

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.models.oauth import OAuthAccessToken, OAuthApplication

from ee.api.agentic_provisioning import AUTH_CODE_CACHE_PREFIX
from ee.api.agentic_provisioning.signature import compute_signature
from ee.api.agentic_provisioning.test.base import HMAC_SECRET, TEST_STRIPE_OAUTH_CLIENT_ID, ProvisioningTestBase
from ee.api.agentic_provisioning.views import (
    STRIPE_CONTRACTED_SCOPES,
    LegacyStripeOAuthAppMissingError,
    _get_legacy_stripe_oauth_app,
)


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestOAuthTokenExchange(ProvisioningTestBase):
    def _set_app_ceiling(self, scopes: list[str]) -> None:
        OAuthApplication.objects.filter(client_id=TEST_STRIPE_OAUTH_CLIENT_ID).update(scopes=scopes)

    def _store_auth_code(self, code: str = "test_code", **overrides):
        data = {
            "user_id": self.user.id,
            "org_id": str(self.organization.id),
            "team_id": self.team.id,
            "stripe_account_id": "acct_123",
            "scopes": ["query:read", "project:read"],
            "region": "US",
        }
        data.update(overrides)
        cache.set(f"{AUTH_CODE_CACHE_PREFIX}{code}", data, timeout=300)
        return code

    def _token_request_body(self, **overrides):
        params = {"grant_type": "authorization_code", "code": "test_code"}
        params.update(overrides)
        return urlencode(params).encode()

    def _post_token(self, body: bytes):
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)
        return self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            headers={"stripe-signature": f"t={ts},v1={sig}", "api-version": "0.1d"},
        )

    def test_valid_code_exchange_returns_tokens(self):
        self._store_auth_code("test_code")
        body = self._token_request_body()
        res = self._post_token(body)
        assert res.status_code == 200
        data = res.json()
        assert data["token_type"] == "bearer"
        assert data["access_token"].startswith("pha_")
        assert data["refresh_token"].startswith("phr_")
        assert data["expires_in"] > 0
        assert "scope" not in data
        assert "account" in data
        assert data["account"]["id"] == str(self.organization.id)
        assert "available_teams" in data["account"]
        assert len(data["account"]["available_teams"]) >= 1
        team_entry = data["account"]["available_teams"][0]
        assert "id" in team_entry
        assert "name" in team_entry
        assert "organization_id" in team_entry

    def test_invalid_code_returns_400(self):
        body = self._token_request_body(code="nonexistent")
        res = self._post_token(body)
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_grant"

    def test_code_is_single_use(self):
        self._store_auth_code("single_use_code")
        body = self._token_request_body(code="single_use_code")
        res1 = self._post_token(body)
        assert res1.status_code == 200
        res2 = self._post_token(body)
        assert res2.status_code == 400

    def test_refresh_token_exchange(self):
        self._store_auth_code("code_for_refresh")
        body = self._token_request_body(code="code_for_refresh")
        first_res = self._post_token(body)
        refresh_token = first_res.json()["refresh_token"]

        refresh_body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        res = self._post_token(refresh_body)
        assert res.status_code == 200
        data = res.json()
        assert data["access_token"].startswith("pha_")
        assert data["refresh_token"].startswith("phr_")
        assert data["access_token"] != first_res.json()["access_token"]

    def test_invalid_refresh_token_returns_400(self):
        body = urlencode({"grant_type": "refresh_token", "refresh_token": "phr_invalid"}).encode()
        res = self._post_token(body)
        assert res.status_code == 400

    def test_unsupported_grant_type_returns_400(self):
        body = urlencode({"grant_type": "client_credentials"}).encode()
        res = self._post_token(body)
        assert res.status_code == 400

    def test_missing_code_returns_400(self):
        body = urlencode({"grant_type": "authorization_code"}).encode()
        res = self._post_token(body)
        assert res.status_code == 400

    def test_refresh_token_is_single_use(self):
        self._store_auth_code("code_for_replay")
        body = self._token_request_body(code="code_for_replay")
        first_res = self._post_token(body)
        refresh_token = first_res.json()["refresh_token"]

        refresh_body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        res1 = self._post_token(refresh_body)
        assert res1.status_code == 200

        res2 = self._post_token(refresh_body)
        assert res2.status_code == 400
        assert res2.json()["error"] == "invalid_grant"

    def test_missing_signature_returns_401(self):
        self._store_auth_code("test_code")
        body = self._token_request_body()
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            headers={"api-version": "0.1d"},
        )
        assert res.status_code == 401

    def test_token_exchange_seeds_stripe_app_scopes(self):
        app = OAuthApplication.objects.get(client_id=TEST_STRIPE_OAUTH_CLIENT_ID)
        app.scopes = []
        app.save(update_fields=["scopes"])

        self._store_auth_code("seed_code")
        res = self._post_token(self._token_request_body(code="seed_code"))

        assert res.status_code == 200
        app.refresh_from_db()
        assert app.scopes == STRIPE_CONTRACTED_SCOPES

    def test_token_exchange_missing_stripe_app_hard_fails(self):
        OAuthApplication.objects.filter(client_id=TEST_STRIPE_OAUTH_CLIENT_ID).delete()

        self._store_auth_code("orphan_code")
        res = self._post_token(self._token_request_body(code="orphan_code"))

        assert res.status_code == 500
        assert res.json()["error"] == "server_error"
        # No app may be fabricated to paper over the missing configuration.
        assert not OAuthApplication.objects.filter(client_id=TEST_STRIPE_OAUTH_CLIENT_ID).exists()

    def test_direct_mint_within_ceiling_grants_requested_scopes(self):
        self._set_app_ceiling(["query:read", "project:read"])
        self._store_auth_code("ceiling_ok", scopes=["query:read"])
        res = self._post_token(self._token_request_body(code="ceiling_ok"))
        assert res.status_code == 200
        token = OAuthAccessToken.objects.get(token=res.json()["access_token"])
        assert token.scope == "query:read"

    def test_direct_mint_outside_ceiling_returns_invalid_scope(self):
        self._set_app_ceiling(["query:read"])
        self._store_auth_code("ceiling_bad", scopes=["query:read", "insight:write"])
        res = self._post_token(self._token_request_body(code="ceiling_bad"))
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_scope"

    def test_refresh_narrows_to_tightened_ceiling(self):
        self._set_app_ceiling(["query:read", "insight:write"])
        self._store_auth_code("refresh_narrow", scopes=["query:read", "insight:write"])
        first = self._post_token(self._token_request_body(code="refresh_narrow"))
        refresh_token = first.json()["refresh_token"]

        self._set_app_ceiling(["query:read"])
        refresh_body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        res = self._post_token(refresh_body)
        assert res.status_code == 200
        token = OAuthAccessToken.objects.get(token=res.json()["access_token"])
        assert token.scope == "query:read"

    def test_refresh_rejected_when_scopes_outside_ceiling(self):
        self._set_app_ceiling(["insight:write"])
        self._store_auth_code("refresh_reject", scopes=["insight:write"])
        first = self._post_token(self._token_request_body(code="refresh_reject"))
        refresh_token = first.json()["refresh_token"]

        self._set_app_ceiling(["query:read"])
        refresh_body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        res = self._post_token(refresh_body)
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_grant"

    def _stamp_session_revoke(self, when=None) -> None:
        OAuthApplication.objects.filter(client_id=TEST_STRIPE_OAUTH_CLIENT_ID).update(
            sessions_revoked_at=when or timezone.now()
        )

    def test_refresh_rejected_when_token_predates_session_revoke(self):
        # Stamp without sweeping, simulating a refresh token the bulk revoke missed.
        self._store_auth_code("revoke_refresh", issued_at=timezone.now().isoformat())
        first = self._post_token(self._token_request_body(code="revoke_refresh"))
        refresh_token = first.json()["refresh_token"]

        self._stamp_session_revoke()

        tokens_before = OAuthAccessToken.objects.count()
        refresh_body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        res = self._post_token(refresh_body)
        assert res.status_code == 400
        body = res.json()
        assert body["error"] == "invalid_grant"
        assert "revoked" in body["error_description"]
        assert OAuthAccessToken.objects.count() == tokens_before

    def test_refresh_allowed_when_token_postdates_session_revoke(self):
        self._stamp_session_revoke(timezone.now() - timedelta(hours=1))
        self._store_auth_code("post_revoke", issued_at=timezone.now().isoformat())
        first = self._post_token(self._token_request_body(code="post_revoke"))
        assert first.status_code == 200

        refresh_body = urlencode(
            {"grant_type": "refresh_token", "refresh_token": first.json()["refresh_token"]}
        ).encode()
        res = self._post_token(refresh_body)
        assert res.status_code == 200

    @parameterized.expand(
        [
            ("issued_before_revoke", -120, 400),
            ("missing_issued_at", None, 400),
            ("issued_after_revoke", 120, 200),
        ]
    )
    def test_code_exchange_against_session_revoke_stamp(self, _name, issued_offset_seconds, expected_status):
        overrides = {}
        if issued_offset_seconds is not None:
            overrides["issued_at"] = (timezone.now() + timedelta(seconds=issued_offset_seconds)).isoformat()
        self._store_auth_code("revoke_code", **overrides)
        self._stamp_session_revoke()

        res = self._post_token(self._token_request_body(code="revoke_code"))
        assert res.status_code == expected_status
        if expected_status == 400:
            assert res.json()["error"] == "invalid_grant"


class TestLegacyStripeOAuthApp(ProvisioningTestBase):
    def _stripe_app(self) -> OAuthApplication:
        return OAuthApplication.objects.get(client_id=TEST_STRIPE_OAUTH_CLIENT_ID)

    @parameterized.expand([("US",), ("EU",)])
    def test_resolves_and_seeds_scopes_regardless_of_region(self, region: str):
        app = self._stripe_app()
        app.scopes = []
        app.save(update_fields=["scopes"])

        with override_settings(CLOUD_DEPLOYMENT=region):
            resolved = _get_legacy_stripe_oauth_app()

        assert resolved.id == app.id
        resolved.refresh_from_db()
        assert resolved.scopes == STRIPE_CONTRACTED_SCOPES

    def test_does_not_overwrite_existing_scopes(self):
        app = self._stripe_app()
        app.scopes = ["query:read"]
        app.save(update_fields=["scopes"])

        resolved = _get_legacy_stripe_oauth_app()

        resolved.refresh_from_db()
        assert resolved.scopes == ["query:read"]

    def test_missing_app_hard_fails_without_fabrication(self):
        OAuthApplication.objects.filter(client_id=TEST_STRIPE_OAUTH_CLIENT_ID).delete()

        with self.assertRaises(LegacyStripeOAuthAppMissingError):
            _get_legacy_stripe_oauth_app()

        assert not OAuthApplication.objects.filter(client_id=TEST_STRIPE_OAUTH_CLIENT_ID).exists()

    def test_unconfigured_client_id_hard_fails(self):
        with override_settings(STRIPE_POSTHOG_OAUTH_CLIENT_ID=""):
            with self.assertRaises(LegacyStripeOAuthAppMissingError):
                _get_legacy_stripe_oauth_app()
