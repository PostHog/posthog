import uuid
from datetime import timedelta
from urllib.parse import urlencode

from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized

from posthog.api.id_jag import JWT_BEARER_GRANT_TYPE
from posthog.api.oauth.client_assertion import PRIVATE_KEY_REQUIRED_MESSAGE
from posthog.constants import AvailableFeature
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthRefreshToken
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team

from products.access_control.backend.models.access_control import AccessControl

from ee.api.agentic_provisioning.constants import AUTH_CODE_CACHE_PREFIX, PARTNER_TOKEN_EXPIRY_SECONDS
from ee.api.agentic_provisioning.test.base import (
    TEST_PARTNER_CLIENT_SECRET,
    TEST_PARTNER_JWKS_URI,
    TEST_PARTNER_SCOPES,
    ProvisioningTestBase,
    provisioning_config,
)

TOKEN_URL = "/api/agentic/oauth/token"
OAUTH_TOKEN_URL = "/oauth/token/"


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

    def _exchange_code(self, code: str, verifier: str, partner: OAuthApplication | None = None):
        return self._post_api(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                **self._client_auth(partner),
            },
        )

    def _refresh(self, refresh_token: str, partner: OAuthApplication | None = None):
        return self._post_api(
            TOKEN_URL,
            {"grant_type": "refresh_token", "refresh_token": refresh_token, **self._client_auth(partner)},
        )

    def _stamp_session_revoke(self, when=None) -> None:
        OAuthApplication.objects.filter(id=self.partner.id).update(sessions_revoked_at=when or timezone.now())

    def _client_secret_partner(self, **provisioning: bool) -> OAuthApplication:
        return OAuthApplication.objects.create(
            client_id="client-secret-token-partner",
            name="Client Secret Token Partner",
            client_secret=TEST_PARTNER_CLIENT_SECRET,
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            scopes=TEST_PARTNER_SCOPES,
            is_provisioning_partner=True,
            _provisioning_config=provisioning_config(active=True, **provisioning),
        )

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

    def test_available_teams_exclude_acl_restricted_teams(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        restricted_team = Team.objects.create_with_data(
            initiating_user=self.user, organization=self.organization, name="Restricted team"
        )
        AccessControl.objects.create(
            team=restricted_team,
            access_level="none",
            resource="project",
            resource_id=str(restricted_team.id),
        )

        data = self._request_bearer_token().json()
        listed = data["account"]["available_teams"]

        assert self.team.id in [team["id"] for team in listed]
        assert restricted_team.id not in [team["id"] for team in listed]
        assert restricted_team.name not in [team["name"] for team in listed]

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

    def _partner_that_dropped_its_key(self, *, public: bool) -> tuple[OAuthApplication, str]:
        """A partner that got its tokens while it signed, then lost its key, as a CIMD refresh does when the
        metadata document drops `jwks_uri`."""
        partner = self._client_secret_partner()
        partner.jwks_uri = TEST_PARTNER_JWKS_URI
        partner.save(update_fields=["jwks_uri"])
        refresh_token = self._request_bearer_token(partner=partner).json()["refresh_token"]

        partner.jwks_uri = None
        update_fields = ["jwks_uri"]
        if public:
            partner.client_type = OAuthApplication.CLIENT_PUBLIC
            partner.client_secret = ""
            update_fields += ["client_type", "client_secret"]
        partner.save(update_fields=update_fields)
        return partner, refresh_token

    @parameterized.expand(
        [
            ("public_code_exchange", True, "authorization_code", TOKEN_URL),
            ("public_refresh", True, "refresh_token", TOKEN_URL),
            ("client_secret_code_exchange", False, "authorization_code", TOKEN_URL),
            ("client_secret_refresh", False, "refresh_token", TOKEN_URL),
            ("public_refresh_at_oauth_token", True, "refresh_token", OAUTH_TOKEN_URL),
            ("client_secret_refresh_at_oauth_token", False, "refresh_token", OAUTH_TOKEN_URL),
        ]
    )
    def test_unsigned_token_request(self, _name: str, public: bool, grant_type: str, url: str) -> None:
        partner, refresh_token = self._partner_that_dropped_its_key(public=public)
        credentials = {"client_id": partner.client_id} if public else self._client_auth(partner)
        if grant_type == "authorization_code":
            code, verifier = self._mint_auth_code(partner=partner)
            body = {"grant_type": grant_type, "code": code, "code_verifier": verifier, **credentials}
        else:
            body = {"grant_type": grant_type, "refresh_token": refresh_token, **credentials}

        with patch("posthoganalytics.capture") as capture:
            res = self._post_api(url, body)

        assert res.status_code == 401, res.json()
        assert res.json()["error"] == "invalid_client"
        assert res.json()["error_description"] == PRIVATE_KEY_REQUIRED_MESSAGE
        tags = {call.kwargs.get("properties", {}).get("provisioning_signing") for call in capture.call_args_list}
        assert "refused" in tags

    @parameterized.expand([("public", True), ("client_secret", False)])
    def test_refused_partner_can_still_revoke_its_tokens(self, _name: str, public: bool) -> None:
        partner, refresh_token = self._partner_that_dropped_its_key(public=public)
        credentials = {"client_id": partner.client_id} if public else self._client_auth(partner)

        res = self._post_api(
            "/oauth/revoke/",
            urlencode({"token": refresh_token, "token_type_hint": "refresh_token", **credentials}).encode(),
            content_type="application/x-www-form-urlencoded",
        )

        assert res.status_code == 200, res.content
        assert not OAuthRefreshToken.objects.filter(token=refresh_token, revoked__isnull=True).exists()

    def test_refused_partner_gets_a_401_from_the_jwt_bearer_grant(self):
        partner = self._client_secret_partner()
        res = self._post_api(
            OAUTH_TOKEN_URL,
            {"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": "not-an-id-jag", **self._client_auth(partner)},
        )

        assert res.status_code == 401
        assert res.json()["error"] == "invalid_client"

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
        verifier, challenge = self._pkce_pair()
        res = self._post_as_partner(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_scopeless",
                "email": "scopeless-user@example.com",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
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

    def test_refresh_issues_partner_lifetime_token(self) -> None:
        first = self._request_bearer_token().json()

        res = self._refresh(first["refresh_token"])

        assert res.status_code == 200
        assert res.json()["expires_in"] == PARTNER_TOKEN_EXPIRY_SECONDS
        token = OAuthAccessToken.objects.get(token=res.json()["access_token"])
        assert token.expires <= timezone.now() + timedelta(seconds=PARTNER_TOKEN_EXPIRY_SECONDS)

    def test_refresh_rejects_partner_whose_flag_was_cleared(self) -> None:
        first = self._request_bearer_token().json()
        OAuthApplication.objects.filter(pk=self.partner.pk).update(is_provisioning_partner=False)

        res = self._refresh(first["refresh_token"])

        assert res.status_code == 400
        assert res.json()["error"] == "invalid_grant"
        refresh_token = OAuthRefreshToken.objects.get(token=first["refresh_token"])
        assert refresh_token.revoked is None
        assert OAuthAccessToken.objects.filter(token=first["access_token"]).exists()

    def test_refresh_rejects_token_of_app_that_is_not_a_partner(self) -> None:
        app = OAuthApplication.objects.create(
            client_id="ordinary-public-client",
            name="Ordinary Public Client",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://client.example.com/callback",
            algorithm="RS256",
            scopes=TEST_PARTNER_SCOPES,
        )
        access_token = OAuthAccessToken.objects.create(
            application=app,
            token="ordinary_access_token",
            user=self.user,
            expires=timezone.now() + timedelta(hours=1),
            scope="query:read",
            scoped_teams=[self.team.id],
        )
        refresh_token = OAuthRefreshToken.objects.create(
            application=app,
            token="ordinary_refresh_token",
            user=self.user,
            access_token=access_token,
            scoped_teams=[self.team.id],
        )

        res = self._post_api(
            TOKEN_URL,
            {"grant_type": "refresh_token", "refresh_token": refresh_token.token, "client_id": app.client_id},
        )

        assert res.status_code == 400
        assert res.json()["error"] == "invalid_grant"
        refresh_token.refresh_from_db()
        assert refresh_token.revoked is None
        assert refresh_token.access_token_id == access_token.id
        assert list(OAuthAccessToken.objects.filter(application=app).values_list("id", flat=True)) == [access_token.id]

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

    def test_refresh_rejected_when_user_deactivated(self):
        first = self._request_bearer_token().json()

        self.user.is_active = False
        self.user.save()

        res = self._refresh(first["refresh_token"])
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_grant"

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
