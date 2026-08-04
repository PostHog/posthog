import json
import time

from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from posthog.api.oauth.client_assertion import CLIENT_ASSERTION_TYPE_JWT_BEARER
from posthog.models.oauth import OAuthAccessToken, OAuthApplication

from ee.api.agentic_provisioning.test.base import TEST_PARTNER_SCOPES, ProvisioningTestBase, provisioning_config

ACCOUNT_REQUESTS_URL = "/api/agentic/provisioning/account_requests"
TOKEN_URL = "/api/agentic/oauth/token"
PARTNER_CLIENT_ID = "https://jwtpartner.example.com/.well-known/oauth-client-metadata.json"
PARTNER_JWKS_URI = "https://jwtpartner.example.com/.well-known/jwks.json"
KID = "jwt-partner-key"

# Generated once for the module: RSA-2048 keygen is ~100ms and no test mutates the key.
PARTNER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
FOREIGN_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@override_settings(SITE_URL="https://us.posthog.com")
class TestPrivateKeyJwtPartner(ProvisioningTestBase):
    """A private_key_jwt partner authenticating end to end, the way a CIMD client that
    published a jwks_uri would."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.private_key = PARTNER_KEY
        public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.private_key.public_key()))
        public_jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
        self.jwks = {"keys": [public_jwk]}

        # Mirrors a real CIMD registration: the client knows itself by its metadata URL, while
        # the client_id column holds the opaque value generated at registration.
        self.jwt_partner = OAuthApplication.objects.create(
            name="JWT Partner",
            client_id="opaque-jwt-partner-client-id",
            is_cimd_client=True,
            cimd_metadata_url=PARTNER_CLIENT_ID,
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            jwks_uri=PARTNER_JWKS_URI,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://jwtpartner.example.com/callback",
            algorithm="RS256",
            scopes=TEST_PARTNER_SCOPES,
            is_provisioning_partner=True,
            _provisioning_config=provisioning_config(
                active=True, can_create_accounts=True, can_provision_resources=True
            ),
        )

    def _assertion(self, **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": PARTNER_CLIENT_ID,
            "sub": PARTNER_CLIENT_ID,
            "aud": "https://us.posthog.com/api/agentic/oauth/token",
            "jti": f"jti-{now}-{overrides.pop('jti_suffix', 'default')}",
            "iat": now,
            "exp": now + 60,
        }
        claims.update(overrides)
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": KID})

    def _assertion_body(self, **overrides) -> dict:
        return {
            "client_assertion": self._assertion(**overrides),
            "client_assertion_type": CLIENT_ASSERTION_TYPE_JWT_BEARER,
        }

    def _post(self, url: str, data: dict):
        with patch("posthog.api.oauth.client_assertion.fetch_client_json_document", return_value=(self.jwks, None)):
            return self._post_api(url, data)

    def test_account_request_authenticates_with_an_assertion(self):
        res = self._post(
            ACCOUNT_REQUESTS_URL,
            {"id": "req_jwt", "email": "jwt-new-user@example.com", **self._assertion_body()},
        )
        assert res.status_code == 200, res.json()
        assert res.json()["type"] == "oauth"

    def test_account_request_rejected_without_an_assertion(self):
        # The client_id is public, so presenting it alone must not authenticate a confidential
        # partner.
        res = self._post_api(
            ACCOUNT_REQUESTS_URL,
            {
                "id": "req_jwt_bare",
                "email": "jwt-bare@example.com",
                "client_id": PARTNER_CLIENT_ID,
                "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                "code_challenge_method": "S256",
            },
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthorized"

    def test_account_request_rejected_when_signed_by_another_key(self):
        now = int(time.time())
        forged = jwt.encode(
            {
                "iss": PARTNER_CLIENT_ID,
                "sub": PARTNER_CLIENT_ID,
                "aud": "https://us.posthog.com/api/agentic/oauth/token",
                "jti": "forged",
                "iat": now,
                "exp": now + 60,
            },
            FOREIGN_KEY,
            algorithm="RS256",
            headers={"kid": KID},
        )
        res = self._post(
            ACCOUNT_REQUESTS_URL,
            {
                "id": "req_forged",
                "email": "forged@example.com",
                "client_assertion": forged,
                "client_assertion_type": CLIENT_ASSERTION_TYPE_JWT_BEARER,
            },
        )
        assert res.status_code == 401

    def test_token_exchange_requires_an_assertion(self):
        code, verifier = self._mint_auth_code(partner=self.jwt_partner)

        res = self._post_api(TOKEN_URL, {"grant_type": "authorization_code", "code": code, "code_verifier": verifier})

        assert res.status_code == 401
        assert res.json()["error"] == "invalid_client"
        # Client authentication runs before the code is consumed, so the caller can retry.
        retry = self._post(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                **self._assertion_body(jti_suffix="retry"),
            },
        )
        assert retry.status_code == 200, retry.json()

    def test_full_flow_from_account_request_to_resource(self):
        verifier, challenge = self._pkce_pair()
        res = self._post(
            ACCOUNT_REQUESTS_URL,
            {
                "id": "req_jwt_flow",
                "email": "jwt-flow@example.com",
                "scopes": ["query:read", "project:read"],
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                **self._assertion_body(jti_suffix="acct"),
            },
        )
        assert res.status_code == 200, res.json()
        code = res.json()["oauth"]["code"]

        tokens = self._post(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                **self._assertion_body(jti_suffix="token"),
            },
        )
        assert tokens.status_code == 200, tokens.json()
        access_token = tokens.json()["access_token"]

        # The access token is an ordinary OAuth credential regardless of how the partner
        # authenticated, so the resource endpoints are unchanged.
        resource = self._post_with_bearer("/api/agentic/provisioning/resources", {}, token=access_token)
        assert resource.status_code == 200, resource.json()
        assert resource.json()["status"] == "complete"

        refreshed = self._post(
            TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "refresh_token": tokens.json()["refresh_token"],
                **self._assertion_body(jti_suffix="refresh"),
            },
        )
        assert refreshed.status_code == 200, refreshed.json()
        assert OAuthAccessToken.objects.filter(token=refreshed.json()["access_token"]).exists()

    def test_assertion_cannot_be_replayed_across_requests(self):
        body = {"id": "req_replay", "email": "replay@example.com", **self._assertion_body()}
        assert self._post(ACCOUNT_REQUESTS_URL, body).status_code == 200

        replayed = self._post(ACCOUNT_REQUESTS_URL, {**body, "id": "req_replay_2", "email": "replay2@example.com"})
        assert replayed.status_code == 401

    @patch("ee.api.agentic_provisioning.authentication.enqueue_cimd_refresh_if_stale")
    def test_authenticating_refreshes_stale_cimd_metadata(self, mock_refresh):
        # This is the only path a confidential CIMD partner takes, so if it did not refresh,
        # the client's metadata document would freeze at whatever it was promoted with and
        # later scope or jwks_uri edits would never be picked up.
        res = self._post(
            ACCOUNT_REQUESTS_URL,
            {"id": "req_refresh", "email": "refresh@example.com", **self._assertion_body()},
        )
        assert res.status_code == 200, res.json()
        mock_refresh.assert_called_once_with(PARTNER_CLIENT_ID)

    def test_github_grant_listing_authenticates_from_the_query_string(self):
        # The listing endpoint is a GET, so there is no body to carry the assertion. Without
        # the query-string fallback a private_key_jwt partner would be locked out of it while
        # a client_secret partner sailed through on the Basic header.
        with patch("posthog.api.oauth.client_assertion.fetch_client_json_document", return_value=(self.jwks, None)):
            res = self.client.get(
                "/api/agentic/provisioning/github/grants/unknown-grant/repositories",
                data={
                    "client_assertion": self._assertion(jti_suffix="listing"),
                    "client_assertion_type": CLIENT_ASSERTION_TYPE_JWT_BEARER,
                },
            )

        # 404 for a grant that does not exist means authentication was accepted; 401/403 would
        # mean it was not.
        assert res.status_code == 404, res.json()
        assert res.json()["error"]["code"] == "grant_not_found"

    def test_github_grants_accepts_a_private_key_jwt_partner(self):
        # These endpoints require a confidential partner. private_key_jwt qualifies, since the
        # assertion proves control of the client just as a secret would.
        res = self._post(
            "/api/agentic/provisioning/github/grants",
            {"code": "", **self._assertion_body()},
        )
        # An empty GitHub code fails validation, which means auth was accepted.
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_request"
