import json
import time

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized

from posthog.api.oauth.client_assertion import CLIENT_ASSERTION_TYPE_JWT_BEARER, PRIVATE_KEY_REQUIRED_MESSAGE
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.user import User

from ee.api.agentic_provisioning.test.base import TEST_PARTNER_SCOPES, ProvisioningTestBase, provisioning_config

ACCOUNT_REQUESTS_URL = "/api/agentic/provisioning/account_requests"
TOKEN_URL = "/api/agentic/oauth/token"
OAUTH_TOKEN_URL = "/oauth/token/"
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

        self.jwt_partner = OAuthApplication.objects.create(
            name="JWT Partner",
            client_id=PARTNER_CLIENT_ID,
            is_cimd_client=True,
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

    def _assertion(self, *, key: rsa.RSAPrivateKey | None = None, **overrides) -> str:
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
        return jwt.encode(claims, key or self.private_key, algorithm="RS256", headers={"kid": KID})

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

    @parameterized.expand(
        [
            # The client_id is public, so presenting it alone must not authenticate a key-based partner.
            ("creates_accounts", {}, 401),
            ("cannot_create_accounts_or_pay", {"can_create_accounts": False}, 401),
        ]
    )
    def test_account_request_without_an_assertion(
        self, _name: str, capabilities: dict[str, bool], expected_status: int
    ) -> None:
        if capabilities:
            self.jwt_partner.update_provisioning(**capabilities)

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

        assert res.status_code == expected_status, res.json()
        if not capabilities:
            assert res.json()["error"] == {"code": "unauthorized", "message": PRIVATE_KEY_REQUIRED_MESSAGE}

    @parameterized.expand(
        [
            ("jwt_bearer_type", CLIENT_ASSERTION_TYPE_JWT_BEARER),
            # An assertion with a missing or wrong type must not fall back to the bare client_id path unverified.
            ("no_type", None),
            ("wrong_type", "urn:ietf:params:oauth:client-assertion-type:saml2-bearer"),
        ]
    )
    def test_account_request_rejected_when_signed_by_another_key(self, _name: str, assertion_type: str | None) -> None:
        body = {
            "id": "req_forged",
            "email": "forged@example.com",
            "client_id": PARTNER_CLIENT_ID,
            "client_assertion": self._assertion(key=FOREIGN_KEY, jti_suffix="forged"),
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        }
        if assertion_type is not None:
            body["client_assertion_type"] = assertion_type

        res = self._post(ACCOUNT_REQUESTS_URL, body)

        assert res.status_code == 401, res.json()
        assert not User.objects.filter(email="forged@example.com").exists()

    @parameterized.expand(
        [
            ("unsigned", None, 401),
            ("signed_by_another_key", CLIENT_ASSERTION_TYPE_JWT_BEARER, 401),
            ("signed_by_another_key_without_a_type", "", 401),
        ]
    )
    def test_token_exchange_assertion(
        self, _name: str, forged_assertion_type: str | None, expected_status: int
    ) -> None:
        code, verifier = self._mint_auth_code(partner=self.jwt_partner)
        body = {"grant_type": "authorization_code", "code": code, "code_verifier": verifier}
        if forged_assertion_type is not None:
            body.update(
                client_assertion=self._assertion(key=FOREIGN_KEY, jti_suffix="forged"),
                client_assertion_type=forged_assertion_type,
            )

        res = self._post(TOKEN_URL, body)

        assert res.status_code == expected_status, res.json()
        if expected_status == 200:
            return
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

    def test_unsigned_refresh_at_the_oauth_token_endpoint(self) -> None:
        code, verifier = self._mint_auth_code(partner=self.jwt_partner)
        tokens = self._post(
            TOKEN_URL,
            {"grant_type": "authorization_code", "code": code, "code_verifier": verifier, **self._assertion_body()},
        )
        assert tokens.status_code == 200, tokens.json()

        with patch("posthoganalytics.capture") as capture:
            res = self._post_api(
                OAUTH_TOKEN_URL,
                {
                    "grant_type": "refresh_token",
                    "refresh_token": tokens.json()["refresh_token"],
                    "client_id": PARTNER_CLIENT_ID,
                },
            )

        assert res.status_code == 401, res.json()
        signing = {call.kwargs.get("properties", {}).get("provisioning_signing") for call in capture.call_args_list}
        assert "refused" in signing

    @parameterized.expand([("non_paying", False), ("paying", True)])
    @patch("posthoganalytics.capture")
    def test_full_flow_from_account_request_to_resource(
        self, _name: str, pays_for_customers: bool, capture: MagicMock
    ) -> None:
        self.jwt_partner.update_provisioning(pays_for_customers=pays_for_customers)
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
        # One each from the account request, the code exchange and the refresh.
        assert [
            call.kwargs["properties"]["provisioning_signing"]
            for call in capture.call_args_list
            if "provisioning_signing" in call.kwargs.get("properties", {})
        ] == ["signed"] * 3

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
