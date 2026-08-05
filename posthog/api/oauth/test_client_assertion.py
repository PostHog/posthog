import json
import time
from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from posthog.api.oauth.cimd import CIMDFetchError
from posthog.api.oauth.client_assertion import (
    CLIENT_ASSERTION_TYPE_JWT_BEARER,
    MAX_ASSERTION_LIFETIME_SECONDS,
    ClientAssertionError,
    extract_client_assertion,
    load_jwks,
    verify_client_assertion,
)
from posthog.models.oauth import OAuthApplication, TokenEndpointAuthMethod

CLIENT_ID = "https://partner.example.com/.well-known/oauth-client-metadata.json"
JWKS_URI = "https://partner.example.com/.well-known/jwks.json"
AUDIENCE = "https://us.posthog.com/api/agentic/oauth/token"
KID = "partner-key-1"


def _rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


# Generated once for the module: RSA-2048 keygen is ~100ms, and no test mutates a key, so
# building one per test method would add seconds to the suite for nothing.
KEY = _rsa_key()
OTHER_KEY = _rsa_key()


def _drf_request(data: dict) -> Request:
    raw = APIRequestFactory().post("/", data, format="json")
    return cast(Request, Request(raw, parsers=[JSONParser()]))


def _jwks_for(private_key, kid: str = KID) -> dict:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


@override_settings(SITE_URL="https://us.posthog.com")
class TestClientAssertion(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.private_key = KEY
        self.jwks = _jwks_for(self.private_key)
        self.app = OAuthApplication.objects.create(
            name="Assertion Partner",
            client_id=CLIENT_ID,
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            jwks_uri=JWKS_URI,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_provisioning_partner=True,
        )

    def _claims(self, **overrides) -> dict:
        now = int(time.time())
        claims = {
            "iss": CLIENT_ID,
            "sub": CLIENT_ID,
            "aud": AUDIENCE,
            "jti": f"jti-{now}-{overrides.pop('jti_suffix', 'default')}",
            "iat": now,
            "exp": now + 60,
        }
        claims.update(overrides)
        return {k: v for k, v in claims.items() if v is not None}

    def _assertion(self, *, key=None, kid: str | None = KID, algorithm: str = "RS256", **overrides) -> str:
        headers = {"kid": kid} if kid else {}
        return jwt.encode(self._claims(**overrides), key or self.private_key, algorithm=algorithm, headers=headers)

    def _verify(self, assertion: str) -> None:
        with patch("posthog.api.oauth.client_assertion.fetch_client_json_document", return_value=(self.jwks, None)):
            verify_client_assertion(self.app, assertion)

    def test_valid_assertion_verifies(self):
        self._verify(self._assertion())

    def test_assertion_is_single_use(self):
        assertion = self._assertion()
        self._verify(assertion)

        # Replaying the same jti must fail even though the signature is still perfectly valid.
        with self.assertRaises(ClientAssertionError):
            self._verify(assertion)

    @parameterized.expand(
        [
            ("wrong_issuer", {"iss": "https://attacker.example.com/metadata.json"}),
            ("wrong_subject", {"sub": "https://attacker.example.com/metadata.json"}),
            ("wrong_audience", {"aud": "https://elsewhere.example.com/token"}),
            ("expired", {"exp": int(time.time()) - 120, "iat": int(time.time()) - 180}),
            ("missing_jti", {"jti": None}),
            ("missing_exp", {"exp": None}),
            # Without iat there is no lower bound to measure the lifetime cap against, so an
            # assertion could name an exp arbitrarily far in the future.
            ("missing_iat", {"iat": None}),
        ]
    )
    def test_rejected_claims(self, _name, overrides):
        with self.assertRaises(ClientAssertionError):
            self._verify(self._assertion(**overrides))

    def test_assertion_signed_by_another_key_is_rejected(self):
        # The whole point of the scheme: only the holder of the published key can authenticate.
        with self.assertRaises(ClientAssertionError):
            self._verify(self._assertion(key=OTHER_KEY))

    def test_hmac_algorithm_is_rejected(self):
        # Key confusion: the public key is published, so if an HMAC family were accepted an
        # attacker could sign with the public key material as the shared secret.
        forged_secret = str(self.private_key.public_key().public_numbers().n)
        assertion = jwt.encode(self._claims(), forged_secret, algorithm="HS256", headers={"kid": KID})
        with self.assertRaises(ClientAssertionError):
            self._verify(assertion)

    def test_unsigned_assertion_is_rejected(self):
        # nosemgrep: python.jwt.security.jwt-none-alg.jwt-python-none-alg (forging an alg=none token is the point: this asserts verify_client_assertion refuses it)
        assertion = jwt.encode(self._claims(), key="", algorithm="none")
        with self.assertRaises(ClientAssertionError):
            self._verify(assertion)

    def test_overlong_lifetime_is_rejected(self):
        now = int(time.time())
        with self.assertRaises(ClientAssertionError):
            self._verify(self._assertion(iat=now, exp=now + MAX_ASSERTION_LIFETIME_SECONDS + 60))

    def test_unknown_kid_is_rejected(self):
        with self.assertRaises(ClientAssertionError):
            self._verify(self._assertion(kid="rotated-out-key"))

    def test_kid_required_when_jwks_holds_several_keys(self):
        self.jwks = {"keys": [*self.jwks["keys"], *_jwks_for(OTHER_KEY, kid="partner-key-2")["keys"]]}
        with self.assertRaises(ClientAssertionError):
            self._verify(self._assertion(kid=None))

    def test_client_not_registered_for_the_method_is_rejected(self):
        # Dropping the key source moves it back to client_secret authentication.
        self.app.jwks_uri = None
        self.app.save(update_fields=["jwks_uri"])
        assert self.app.token_endpoint_auth_method is TokenEndpointAuthMethod.CLIENT_SECRET_POST
        with self.assertRaises(ClientAssertionError):
            self._verify(self._assertion())

    def test_jwks_is_cached_across_verifications(self):
        with patch(
            "posthog.api.oauth.client_assertion.fetch_client_json_document", return_value=(self.jwks, None)
        ) as fetch:
            verify_client_assertion(self.app, self._assertion(jti_suffix="a"))
            verify_client_assertion(self.app, self._assertion(jti_suffix="b"))
            # A second exchange must not mean a second outbound fetch.
            fetch.assert_called_once()

    def test_jwks_fetch_failure_is_negatively_cached(self):
        with patch(
            "posthog.api.oauth.client_assertion.fetch_client_json_document",
            side_effect=CIMDFetchError("unreachable"),
        ) as fetch:
            for _ in range(3):
                with self.assertRaises(ClientAssertionError):
                    load_jwks(JWKS_URI)
            # A client with a broken jwks_uri must not turn each request into an outbound fetch.
            fetch.assert_called_once()

    def test_jwks_with_too_many_keys_is_rejected(self):
        # The cap is on key count, so the same key material under distinct kids exercises it.
        many = {"keys": [_jwks_for(KEY, kid=f"k{i}")["keys"][0] for i in range(11)]}
        with patch("posthog.api.oauth.client_assertion.fetch_client_json_document", return_value=(many, None)):
            with self.assertRaises(ClientAssertionError):
                load_jwks(JWKS_URI)

    @parameterized.expand(
        [
            ("wrong_type", {"client_assertion": "x.y.z", "client_assertion_type": "urn:something:else"}),
            ("missing_type", {"client_assertion": "x.y.z"}),
            ("missing_assertion", {"client_assertion_type": CLIENT_ASSERTION_TYPE_JWT_BEARER}),
            ("empty", {}),
        ]
    )
    def test_no_assertion_extracted(self, _name, data):
        assert extract_client_assertion(_drf_request(data)) is None

    def test_assertion_client_id_falls_back_to_subject(self):
        # RFC 7521 section 4.2 lets the assertion carry the identity, so a caller may omit
        # client_id entirely.
        assertion = self._assertion()
        request = _drf_request(
            {"client_assertion": assertion, "client_assertion_type": CLIENT_ASSERTION_TYPE_JWT_BEARER}
        )
        assert extract_client_assertion(request) == (assertion, CLIENT_ID)
