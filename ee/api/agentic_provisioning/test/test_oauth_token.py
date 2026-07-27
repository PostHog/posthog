import uuid
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized

from posthog.models.oauth import OAuthAccessToken, OAuthApplication

from ee.api.agentic_provisioning import AUTH_CODE_CACHE_PREFIX
from ee.api.agentic_provisioning.test.base import TEST_PARTNER_SCOPES, ProvisioningTestBase

TOKEN_URL = "/api/agentic/oauth/token"


class TestOAuthTokenExchange(ProvisioningTestBase):
    def _set_app_ceiling(self, scopes: list[str]) -> None:
        OAuthApplication.objects.filter(id=self.partner.id).update(scopes=scopes)

    def _mint_code_with_overrides(self, scopes: list[str] | None = None, **overrides) -> tuple[str, str]:
        code, verifier = self._mint_auth_code(scopes=scopes)
        key = f"{AUTH_CODE_CACHE_PREFIX}{code}"
        data = cache.get(key)
        for field, value in overrides.items():
            if value is None:
                data.pop(field, None)
            else:
                data[field] = value
        cache.set(key, data, timeout=300)
        return code, verifier

    def _exchange_code(self, code: str, verifier: str):
        return self._post_api(TOKEN_URL, {"grant_type": "authorization_code", "code": code, "code_verifier": verifier})

    def _refresh(self, refresh_token: str):
        return self._post_api(TOKEN_URL, {"grant_type": "refresh_token", "refresh_token": refresh_token})

    def _stamp_session_revoke(self, when=None) -> None:
        OAuthApplication.objects.filter(id=self.partner.id).update(sessions_revoked_at=when or timezone.now())

    def test_valid_code_exchange_returns_tokens(self):
        res = self._request_bearer_token()
        assert res.status_code == 200
        data = res.json()
        assert data["token_type"] == "bearer"
        assert data["access_token"].startswith("pha_")
        assert data["refresh_token"].startswith("phr_")
        assert data["expires_in"] > 0
        assert "scope" not in data
        assert data["account"]["id"] == str(self.organization.id)
        assert len(data["account"]["available_teams"]) >= 1
        team_entry = data["account"]["available_teams"][0]
        assert "id" in team_entry
        assert "name" in team_entry
        assert "organization_id" in team_entry

    def test_code_is_single_use(self):
        code, verifier = self._mint_auth_code()
        assert self._exchange_code(code, verifier).status_code == 200
        res = self._exchange_code(code, verifier)
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_grant"

    @parameterized.expand(
        [
            (
                "invalid_code",
                {"grant_type": "authorization_code", "code": "nonexistent", "code_verifier": "x"},
                "invalid_grant",
            ),
            ("missing_code", {"grant_type": "authorization_code"}, "invalid_request"),
            ("unsupported_grant_type", {"grant_type": "client_credentials"}, "unsupported_grant_type"),
            ("invalid_refresh_token", {"grant_type": "refresh_token", "refresh_token": "phr_invalid"}, "invalid_grant"),
        ]
    )
    def test_rejected_grants(self, _name, params, error):
        res = self._post_api(TOKEN_URL, params)
        assert res.status_code == 400
        assert res.json()["error"] == error

    def test_code_without_challenge_requires_authentication(self):
        code, verifier = self._mint_code_with_overrides(code_challenge=None, code_challenge_method=None)
        res = self._exchange_code(code, verifier)
        assert res.status_code == 401
        assert res.json() == {"error": "invalid_request", "error_description": "Authentication required"}

    def test_missing_code_verifier_returns_401(self):
        code, _verifier = self._mint_auth_code()
        res = self._post_api(TOKEN_URL, {"grant_type": "authorization_code", "code": code})
        assert res.status_code == 401
        assert res.json()["error_description"] == "code_verifier is required for PKCE"

    def test_pkce_mismatch_returns_400_without_consuming_code(self):
        code, verifier = self._mint_auth_code()
        res = self._exchange_code(code, "wrong_verifier_" + "a" * 32)
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_grant"
        # Verification runs before the code is consumed, so a failed attempt must not burn it.
        assert self._exchange_code(code, verifier).status_code == 200

    @parameterized.expand([("unknown_partner", str(uuid.uuid4())), ("missing_partner", "")])
    def test_code_without_resolvable_partner_returns_invalid_grant(self, _name, partner_id):
        code, verifier = self._mint_code_with_overrides(partner_id=partner_id)
        res = self._exchange_code(code, verifier)
        assert res.status_code == 400
        assert res.json() == {
            "error": "invalid_grant",
            "error_description": "Unknown application for this authorization code",
        }

    def test_code_with_empty_scopes_rejected(self):
        code, verifier = self._mint_auth_code(scopes=[])
        res = self._exchange_code(code, verifier)
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_scope"

    def test_omitted_request_scopes_resolve_to_app_ceiling(self):
        partner_token = self._get_bearer_token()
        verifier, challenge = self._pkce_pair()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_scopeless",
                "email": "scopeless-user@example.com",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            token=partner_token,
        )
        assert res.status_code == 200
        code = res.json()["oauth"]["code"]

        exchange = self._exchange_code(code, verifier)
        assert exchange.status_code == 200
        token = OAuthAccessToken.objects.get(token=exchange.json()["access_token"])
        assert set(token.scope.split()) == set(TEST_PARTNER_SCOPES)

    def test_refresh_token_rotation_is_single_use(self):
        first = self._request_bearer_token().json()
        res = self._refresh(first["refresh_token"])
        assert res.status_code == 200
        rotated = res.json()
        assert rotated["access_token"].startswith("pha_")
        assert rotated["refresh_token"].startswith("phr_")
        assert rotated["access_token"] != first["access_token"]
        assert rotated["refresh_token"] != first["refresh_token"]

        replay = self._refresh(first["refresh_token"])
        assert replay.status_code == 400
        assert replay.json()["error"] == "invalid_grant"

    def test_direct_mint_within_ceiling_grants_requested_scopes(self):
        self._set_app_ceiling(["query:read", "project:read"])
        code, verifier = self._mint_auth_code(scopes=["query:read"])
        res = self._exchange_code(code, verifier)
        assert res.status_code == 200
        token = OAuthAccessToken.objects.get(token=res.json()["access_token"])
        assert token.scope == "query:read"

    def test_direct_mint_outside_ceiling_returns_invalid_scope(self):
        self._set_app_ceiling(["query:read"])
        code, verifier = self._mint_auth_code(scopes=["query:read", "insight:write"])
        res = self._exchange_code(code, verifier)
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_scope"

    def test_refresh_narrows_to_tightened_ceiling(self):
        self._set_app_ceiling(["query:read", "insight:write"])
        first = self._request_bearer_token(scopes=["query:read", "insight:write"]).json()

        self._set_app_ceiling(["query:read"])
        res = self._refresh(first["refresh_token"])
        assert res.status_code == 200
        token = OAuthAccessToken.objects.get(token=res.json()["access_token"])
        assert token.scope == "query:read"

    def test_refresh_rejected_when_scopes_outside_ceiling(self):
        self._set_app_ceiling(["insight:write"])
        first = self._request_bearer_token(scopes=["insight:write"]).json()

        self._set_app_ceiling(["query:read"])
        res = self._refresh(first["refresh_token"])
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_grant"

    def test_refresh_rejected_when_token_predates_session_revoke(self):
        # Stamp without sweeping, simulating a refresh token the bulk revoke missed.
        first = self._request_bearer_token().json()
        self._stamp_session_revoke()

        tokens_before = OAuthAccessToken.objects.count()
        res = self._refresh(first["refresh_token"])
        assert res.status_code == 400
        body = res.json()
        assert body["error"] == "invalid_grant"
        assert "revoked" in body["error_description"]
        assert OAuthAccessToken.objects.count() == tokens_before

    def test_refresh_allowed_when_token_postdates_session_revoke(self):
        self._stamp_session_revoke(timezone.now() - timedelta(hours=1))
        first = self._request_bearer_token()
        assert first.status_code == 200

        res = self._refresh(first.json()["refresh_token"])
        assert res.status_code == 200

    @parameterized.expand(
        [
            ("issued_before_revoke", -120, 400),
            ("missing_issued_at", None, 400),
            ("issued_after_revoke", 120, 200),
        ]
    )
    def test_code_exchange_against_session_revoke_stamp(self, _name, issued_offset_seconds, expected_status):
        issued_at = (
            (timezone.now() + timedelta(seconds=issued_offset_seconds)).isoformat()
            if issued_offset_seconds is not None
            else None
        )
        code, verifier = self._mint_code_with_overrides(issued_at=issued_at)
        self._stamp_session_revoke()

        res = self._exchange_code(code, verifier)
        assert res.status_code == expected_status
        if expected_status == 400:
            assert res.json()["error"] == "invalid_grant"
