"""
Tests for the ID-JAG token endpoint + the resource-server side
authentication backend.

The strategy is:
  * Generate a throwaway RSA keypair in `setUpClass` and use it to sign a
    synthetic IdP-issued ID-JAG. We patch `posthog.api.id_jag._get_jwks_client`
    to return a `PyJWK` whose `.key` is the matching public key so signature
    verification succeeds without HTTP calls.
  * For access tokens, we use the OIDC private key already configured for OAuth
    by overriding `settings.OIDC_RSA_PRIVATE_KEY` (mirrors the OAuth test suite).
"""

import time
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

import jwt
from cryptography.hazmat.primitives import serialization
from oauth2_provider.utils import jwk_from_pem
from rest_framework import status

from posthog.api.id_jag import (
    ACCESS_TOKEN_TYPE,
    ID_JAG_TOKEN_TYPE,
    JWT_BEARER_GRANT_TYPE,
    _get_scopes,
    _get_sub,
    issue_access_token,
)
from posthog.auth import IDJagAccessTokenAuthentication
from posthog.constants import AvailableFeature
from posthog.models.identity_provider_config import IdentityProviderConfig
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User as UserModel
from posthog.settings.utils import generate_rsa_private_key_pem

# rsa operations are expensive, keep this at the module-level to avoid slow tests
_IDP_PRIVATE_KEY_PEM = generate_rsa_private_key_pem()
_AS_PRIVATE_KEY_PEM = generate_rsa_private_key_pem()

_IDP_ISSUER = "https://idp.example.com"
_VERIFIED_DOMAIN = "example.com"
_PROVIDER_NAME = _VERIFIED_DOMAIN
_SITE_URL = "https://posthog.test"
_AUTH_SERVER_URL = _SITE_URL
_RESOURCE_URL = _SITE_URL
_RESOURCE_CLIENT_ID = "client_abc-at-posthog"


def _public_key_for(pem: str) -> Any:
    return serialization.load_pem_private_key(pem.encode(), password=None).public_key()


def _make_id_jag(
    *,
    issuer: str = _IDP_ISSUER,
    sub: str = "user@example.com",
    audience: str = _AUTH_SERVER_URL,
    client_id: str = _RESOURCE_CLIENT_ID,
    resource: str = _RESOURCE_URL,
    scope: str = "feature_flag:read feature_flag:write",
    iat: int | None = None,
    nbf: int | None = None,
    exp_seconds: int = 300,
    typ_header: str = ID_JAG_TOKEN_TYPE,
    extra_claims: dict[str, Any] | None = None,
    signing_pem: str | None = None,
) -> str:
    """Forge a synthetic IdP-issued ID-JAG for the test suite."""

    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": issuer,
        "sub": sub,
        "aud": audience,
        "client_id": client_id,
        "resource": resource,
        "scope": scope,
        "jti": f"id-jag-{now}",
        "iat": iat if iat is not None else now,
        "nbf": nbf if nbf is not None else now,
        "exp": now + exp_seconds,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(
        payload,
        signing_pem or _IDP_PRIVATE_KEY_PEM,
        algorithm="RS256",
        headers={"typ": typ_header, "alg": "RS256"},
    )


@override_settings(
    OIDC_RSA_PRIVATE_KEY=_AS_PRIVATE_KEY_PEM,
    SITE_URL=_SITE_URL,
    ID_JAG_ACCESS_TOKEN_TTL_SECONDS=300,
    ID_JAG_CLOCK_SKEW_SECONDS=30,
    CORS_ALLOW_ALL_ORIGINS=True,
)
class TestIdJagTokenEndpoint(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.user.email = "user@example.com"
        cls.user.save()
        cls.organization.available_product_features = [
            {"key": AvailableFeature.XAA_AUTHENTICATION, "name": "XAA Authentication"}
        ]
        cls.organization.save()
        domain = OrganizationDomain.objects.create(
            organization=cls.organization,
            domain=_VERIFIED_DOMAIN,
            verified_at=timezone.now(),
        )
        domain.identity_provider_config = IdentityProviderConfig.objects.create(
            organization=cls.organization, id_jag_issuer_url=_IDP_ISSUER
        )
        domain.save()

    def setUp(self) -> None:
        super().setUp()

        # Stub the JWKS fetch so PyJWKClient resolves to our test public key
        # without hitting the network. `get_signing_key_from_jwt` is the only
        # surface area we use.
        signing_key = MagicMock()
        signing_key.key = _public_key_for(_IDP_PRIVATE_KEY_PEM)
        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.return_value = signing_key

        self._jwks_patch = patch("posthog.api.id_jag._get_jwks_client", return_value=mock_jwks_client)
        self._jwks_patch.start()
        self.addCleanup(self._jwks_patch.stop)

    def _post_token(self, body: dict[str, Any]) -> Any:
        return self.client.post("/oauth/token", data=body, content_type="application/json")

    def test_issues_access_token_for_valid_id_jag(self) -> None:
        assertion = _make_id_jag()
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        body = resp.json()
        self.assertEqual(body["token_type"], "Bearer")
        self.assertEqual(body["expires_in"], 300)
        self.assertEqual(set(body["scope"].split()), {"feature_flag:read", "feature_flag:write"})

        claims = jwt.decode(
            body["access_token"],
            _public_key_for(_AS_PRIVATE_KEY_PEM),
            algorithms=["RS256"],
            audience=_RESOURCE_URL,
            issuer=_AUTH_SERVER_URL,
        )
        self.assertEqual(claims["sub"], f"{_PROVIDER_NAME}:user@example.com")
        self.assertEqual(claims["aud"], _RESOURCE_URL)
        self.assertEqual(claims["client_id"], _RESOURCE_CLIENT_ID)
        self.assertEqual(claims["app_org"], _PROVIDER_NAME)
        self.assertIn("jti", claims)
        self.assertIn("iat", claims)
        self.assertIn("exp", claims)

        header = jwt.get_unverified_header(body["access_token"])
        self.assertEqual(header["typ"], ACCESS_TOKEN_TYPE)
        self.assertEqual(header["alg"], "RS256")
        # kid matches the JWKS thumbprint so resource servers can select the key during rotation
        self.assertEqual(header["kid"], jwk_from_pem(_AS_PRIVATE_KEY_PEM).thumbprint())

    def test_rejects_when_org_lacks_xaa_billing_feature(self) -> None:
        # XAA is billing-gated: even a fully valid ID-JAG must be rejected when
        # the organization that owns the verified domain is not entitled. The
        # check runs after signature + membership verification, so the failure
        # surfaces as access_denied (403) rather than the generic rejection.
        self.organization.available_product_features = []
        self.organization.save()

        assertion = _make_id_jag()
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.json()["error"], "access_denied")

    def test_issue_access_token_helper_rejects_without_billing_feature(self) -> None:
        self.organization.available_product_features = []
        self.organization.save()

        from posthog.api.id_jag import AccessDeniedError

        assertion = _make_id_jag()
        with self.assertRaises(AccessDeniedError):
            issue_access_token(assertion, requested_scope=None, request_client_id=None)

    def test_email_claim_is_preferred_over_sub_for_user_lookup(self) -> None:
        # IdPs are not required to put an email in `sub` — it may be an opaque
        # stable identifier. When the `email` claim is present we should use it
        # for domain verification and membership lookup; `sub` is still stamped
        # into the issued access token as the subject identifier.
        opaque_sub = "auth0|abc123"
        assertion = _make_id_jag(sub=opaque_sub, extra_claims={"email": "user@example.com"})
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        claims = jwt.decode(
            resp.json()["access_token"],
            _public_key_for(_AS_PRIVATE_KEY_PEM),
            algorithms=["RS256"],
            audience=_RESOURCE_URL,
            issuer=_AUTH_SERVER_URL,
        )
        # The stamped sub preserves the IdP's opaque identifier; the resolved
        # PostHog user identity is stamped separately into `email` so the
        # resource-side authenticator can find the User row without trying to
        # parse an email out of `sub`.
        self.assertEqual(claims["sub"], f"{_PROVIDER_NAME}:{opaque_sub}")
        self.assertEqual(claims["email"], "user@example.com")

    def test_round_trip_with_opaque_sub_authenticates_on_resource_side(self) -> None:
        # Regression: opaque-sub IdPs (Okta, Auth0, Entra) emit `sub` values
        # that aren't emails. Issuance was already keyed off the `email`
        # claim, but the resource-side authenticator was keying off the
        # userSub half of `sub` — which 401'd every request. Drive the whole
        # flow end-to-end here: real /oauth/token → real /api/users/@me/.
        assertion = _make_id_jag(
            sub="auth0|opaque-id-abc123",
            scope="user:read",
            extra_claims={"email": "user@example.com", "email_verified": True},
        )
        issue_resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(issue_resp.status_code, status.HTTP_200_OK, issue_resp.content)
        access_token = issue_resp.json()["access_token"]

        api_resp = self.client.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {access_token}")
        self.assertEqual(api_resp.status_code, status.HTTP_200_OK, api_resp.content)
        self.assertEqual(api_resp.json()["email"], "user@example.com")

    def test_rejects_when_email_claim_is_explicitly_unverified(self) -> None:
        # OIDC Core §5.1 — the `email` claim is mutable; only the IdP's
        # `email_verified` boolean signals ownership. Without this gate, a
        # user authenticated under their own `sub` could set the `email`
        # claim to a victim's address and slip past the membership check.
        assertion = _make_id_jag(
            sub="auth0|attacker",
            extra_claims={"email": "user@example.com", "email_verified": False},
        )
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")
        self.assertEqual(resp.json()["error_description"], "ID-JAG could not be verified")

    def test_accepts_when_email_verified_is_true(self) -> None:
        assertion = _make_id_jag(
            sub="auth0|abc123",
            extra_claims={"email": "user@example.com", "email_verified": True},
        )
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_accepts_when_email_verified_is_omitted(self) -> None:
        # Many valid IdPs (notably Okta in some configs) omit `email_verified`
        # rather than emitting `true`. Requiring it true would break them, so
        # we only reject the explicit-false case.
        assertion = _make_id_jag(
            sub="auth0|abc123",
            extra_claims={"email": "user@example.com"},
        )
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_email_verified_false_is_ignored_when_no_email_claim_is_present(self) -> None:
        # The gate only matters when we're about to trust the `email` claim.
        # If the IdP didn't send one, the membership lookup falls back to
        # `sub` and `email_verified: false` is irrelevant.
        assertion = _make_id_jag(
            sub="user@example.com",
            extra_claims={"email_verified": False},
        )
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_rejects_when_email_claim_domain_is_not_verified(self) -> None:
        # When the `email` claim is present it takes precedence — a verified-
        # domain email in `sub` should not rescue an unverified `email` claim.
        assertion = _make_id_jag(
            sub="user@example.com",
            extra_claims={"email": "user@unverified.example"},
        )
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")
        self.assertEqual(resp.json()["error_description"], "ID-JAG could not be verified")

    def test_intersection_with_requested_scope(self) -> None:
        assertion = _make_id_jag(scope="feature_flag:read feature_flag:write dashboard:read")
        resp = self._post_token(
            {
                "grant_type": JWT_BEARER_GRANT_TYPE,
                "assertion": assertion,
                "scope": "feature_flag:read dashboard:write",
            }
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Only feature_flag:read intersects — dashboard:write was not in ID-JAG.
        self.assertEqual(resp.json()["scope"], "feature_flag:read")

    def test_empty_intersection_still_issues_token(self) -> None:
        """https://xaa.dev/docs/token-structure#scope-intersection-rule

        The AS issues a token with empty scope; the resource server is the one
        that denies with 403 insufficient_scope.
        """
        assertion = _make_id_jag(scope="feature_flag:read")
        resp = self._post_token(
            {
                "grant_type": JWT_BEARER_GRANT_TYPE,
                "assertion": assertion,
                "scope": "dashboard:read",
            }
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["scope"], "")

    def test_unknown_scopes_in_id_jag_are_dropped(self) -> None:
        """We never propagate scope strings we don't recognize as PostHog scopes —
        otherwise a malformed IdP could smuggle arbitrary tokens into requests."""
        assertion = _make_id_jag(scope="feature_flag:read totally_bogus:thing")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["scope"], "feature_flag:read")

    def test_accepts_form_urlencoded_body(self) -> None:
        from urllib.parse import urlencode

        assertion = _make_id_jag()
        resp = self.client.post(
            "/oauth/token",
            data=urlencode({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion}),
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_accepts_form_urlencoded_body_with_charset_suffix(self) -> None:
        # RFC 6749 doesn't pin the charset, and real-world clients tack on a
        # `; charset=utf-8` (or UTF-8) — DRF's FormParser must still match.
        from urllib.parse import urlencode

        assertion = _make_id_jag()
        resp = self.client.post(
            "/oauth/token",
            data=urlencode({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion}),
            content_type="application/x-www-form-urlencoded; charset=UTF-8",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_form_urlencoded_with_scope_parameter(self) -> None:
        # Scope is a space-separated string per RFC 6749 §3.3 and must survive
        # the form-encoded round-trip without being treated as a multi-value.
        from urllib.parse import urlencode

        assertion = _make_id_jag(scope="feature_flag:read feature_flag:write")
        resp = self.client.post(
            "/oauth/token",
            data=urlencode(
                {
                    "grant_type": JWT_BEARER_GRANT_TYPE,
                    "assertion": assertion,
                    "scope": "feature_flag:read",
                }
            ),
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["scope"], "feature_flag:read")

        # Error responses must also carry the CORS header — that's the whole
        # point of this test (the body would otherwise be hidden in DevTools).
        bad = self.client.post(
            "/oauth/token",
            data={"grant_type": JWT_BEARER_GRANT_TYPE},
            content_type="application/json",
            HTTP_ORIGIN="https://example.com",
        )
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(bad.json()["error"], "invalid_request")
        self.assertIn("Access-Control-Allow-Origin", bad.headers)

    def test_cors_preflight(self) -> None:
        # Preflight (OPTIONS) needs to succeed before browsers will send the
        # actual POST. The CORS middleware short-circuits this when the path
        # matches `CORS_URLS_REGEX`.
        resp = self.client.options(
            "/oauth/token",
            HTTP_ORIGIN="https://example.com",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("Access-Control-Allow-Origin", resp.headers)
        self.assertIn("Access-Control-Allow-Methods", resp.headers)
        self.assertIn("POST", resp.headers["Access-Control-Allow-Methods"])

    def test_missing_assertion(self) -> None:
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_request")

    def test_rejects_wrong_typ_header(self) -> None:
        assertion = _make_id_jag(typ_header="JWT")  # not oauth-id-jag+jwt
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        body = resp.json()
        self.assertEqual(body["error"], "invalid_grant")
        self.assertIn(ID_JAG_TOKEN_TYPE, body["error_description"])

    def test_rejects_unverified_domain_in_sub(self) -> None:
        # Trust is rooted in the verified-domain → org mapping. An ID-JAG whose
        # `sub` doesn't belong to a verified domain on any PostHog org is
        # rejected with the uniform pre-signature error so we don't leak which
        # domains a tenant has verified.
        assertion = _make_id_jag(sub="someone@not-verified.example.org")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")
        self.assertEqual(resp.json()["error_description"], "ID-JAG could not be verified")

    def test_rejects_when_no_matching_user_exists(self) -> None:
        # Domain is verified but no User row exists for the sub email — fail
        # fast at issuance so we don't mint a token that 401s on every API call.
        assertion = _make_id_jag(sub="ghost@example.com")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")
        self.assertIn("active member", resp.json()["error_description"])

    def test_rejects_when_user_is_inactive(self) -> None:
        # An existing user that has been deactivated should not be able to
        # receive a token via ID-JAG.
        self.user.is_active = False
        self.user.save()
        try:
            assertion = _make_id_jag()
            resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(resp.json()["error"], "invalid_grant")
            self.assertIn("active member", resp.json()["error_description"])
        finally:
            self.user.is_active = True
            self.user.save()

    def test_rejects_when_user_belongs_to_different_org(self) -> None:
        # Cross-org attack: attacker's org verifies a domain, then tries to mint
        # tokens for users at that domain who actually belong to a DIFFERENT
        # org. With the org-membership check, signature + domain verification
        # alone is not enough — the user must belong to the org that owns the
        # verified domain.

        attacker_org = Organization.objects.create(name="attacker-org")
        attacker_domain = OrganizationDomain.objects.create(
            organization=attacker_org,
            domain="bigco.example",
            verified_at=timezone.now(),
        )
        attacker_domain.identity_provider_config = IdentityProviderConfig.objects.create(
            organization=attacker_org, id_jag_issuer_url=_IDP_ISSUER
        )
        attacker_domain.save()

        # Victim user whose email is on the attacker's verified domain but who
        # belongs to a completely unrelated org.
        unrelated_org = Organization.objects.create(name="unrelated-org")
        victim = UserModel.objects.create_user(
            email="victim@bigco.example",
            password="x",
            first_name="V",
        )
        OrganizationMembership.objects.create(organization=unrelated_org, user=victim)

        assertion = _make_id_jag(sub="victim@bigco.example")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")
        self.assertIn("active member", resp.json()["error_description"])

    def test_rejects_signature_from_unrecognized_key(self) -> None:
        other_pem = generate_rsa_private_key_pem()
        assertion = _make_id_jag(signing_pem=other_pem)
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")

    def test_rejects_expired_id_jag(self) -> None:
        assertion = _make_id_jag(exp_seconds=-60)
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")
        self.assertIn("expired", resp.json()["error_description"].lower())

    def test_rejects_nbf_in_future(self) -> None:
        future = int(time.time()) + 120  # past the 30s leeway
        assertion = _make_id_jag(nbf=future)
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")
        self.assertIn("not yet valid", resp.json()["error_description"].lower())

    def test_rejects_iat_in_future_beyond_skew(self) -> None:
        future = int(time.time()) + 120
        # PyJWT validates iat in the future beyond `leeway` as
        # ImmatureSignatureError (https://pyjwt.readthedocs.io/) — we just need
        # to confirm the error surfaces as invalid_grant per ID-JAG spec.
        assertion = _make_id_jag(iat=future, nbf=future - 200)
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")

    def test_accepts_iat_in_future_within_skew(self) -> None:
        future = int(time.time()) + 10  # within 30s skew
        assertion = _make_id_jag(iat=future, nbf=future - 200)
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_rejects_aud_mismatch(self) -> None:
        assertion = _make_id_jag(audience="https://different-as.example.com")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")

    def test_rejects_missing_required_claims(self) -> None:
        assertion = jwt.encode(
            {
                "iss": _IDP_ISSUER,
                "sub": "user@example.com",
                "aud": _AUTH_SERVER_URL,
                # client_id intentionally missing
                "resource": _RESOURCE_URL,
                "scope": "feature_flag:read",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
            },
            _IDP_PRIVATE_KEY_PEM,
            algorithm="RS256",
            headers={"typ": ID_JAG_TOKEN_TYPE},
        )
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")

    def test_rejects_request_client_id_mismatch(self) -> None:
        assertion = _make_id_jag(client_id="client_abc-at-posthog")
        resp = self._post_token(
            {
                "grant_type": JWT_BEARER_GRANT_TYPE,
                "assertion": assertion,
                "client_id": "client_DIFFERENT-at-posthog",
            }
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")

    def test_arbitrary_client_id_is_accepted_when_no_allowlist(self) -> None:
        # When `OrganizationDomain.id_jag_allowed_clients` is empty (the default),
        # any `client_id` value passes — the IdP signature is the binding.
        # We still require the claim to be present.
        assertion = _make_id_jag(client_id="client_anything-at-posthog")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        body = resp.json()
        claims = jwt.decode(
            body["access_token"],
            _public_key_for(_AS_PRIVATE_KEY_PEM),
            algorithms=["RS256"],
            audience=_RESOURCE_URL,
            issuer=_AUTH_SERVER_URL,
        )
        self.assertEqual(claims["client_id"], "client_anything-at-posthog")

    def test_rejects_resource_not_matching_site_url(self) -> None:
        assertion = _make_id_jag(resource="https://other-resource.example.com")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_target")

    @override_settings(ID_JAG_ALLOWED_AUDIENCES=["https://oauth.posthog.com"])
    def test_accepts_aud_matching_configured_allowed_audience(self) -> None:
        # A spec-compliant client derives `aud` from the advertised auth-server issuer
        # (the OAuth proxy), not SITE_URL. That value must be accepted when allowlisted.
        assertion = _make_id_jag(audience="https://oauth.posthog.com")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)

    @override_settings(ID_JAG_ALLOWED_RESOURCES=["https://mcp.posthog.com"])
    def test_accepts_resource_matching_configured_allowed_resource(self) -> None:
        # The ID-JAG `resource` is the advertised resource-server identifier, not SITE_URL.
        # The minted access token is audience-restricted to that resource (EMA §5.1).
        assertion = _make_id_jag(resource="https://mcp.posthog.com/")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        claims = jwt.decode(
            resp.json()["access_token"],
            _public_key_for(_AS_PRIVATE_KEY_PEM),
            algorithms=["RS256"],
            audience="https://mcp.posthog.com",
            issuer=_AUTH_SERVER_URL,
        )
        self.assertEqual(claims["aud"], "https://mcp.posthog.com")

    @override_settings(ID_JAG_ALLOWED_RESOURCES=["https://mcp.posthog.com"])
    def test_round_trip_with_allowed_resource_authenticates_on_resource_side(self) -> None:
        # End-to-end: a token minted for an allowlisted resource must be accepted by the
        # resource server (IDJagAccessTokenAuthentication), not just issued.
        assertion = _make_id_jag(
            resource="https://mcp.posthog.com",
            scope="user:read",
            extra_claims={"email": "user@example.com", "email_verified": True},
        )
        issue_resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(issue_resp.status_code, status.HTTP_200_OK, issue_resp.content)
        access_token = issue_resp.json()["access_token"]

        api_resp = self.client.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {access_token}")
        self.assertEqual(api_resp.status_code, status.HTTP_200_OK, api_resp.content)
        self.assertEqual(api_resp.json()["email"], "user@example.com")

    def test_rejects_when_domain_has_no_id_jag_issuer_configured(self) -> None:
        # ID-JAG is opt-in per domain. With `id_jag_issuer_url` cleared, an
        # otherwise valid ID-JAG must be rejected — the org hasn't bound an IdP yet.
        domain = OrganizationDomain.objects.get(domain=_VERIFIED_DOMAIN)
        config = domain.identity_provider_config
        config.id_jag_issuer_url = None
        config.save()

        assertion = _make_id_jag()
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")
        # Uniform response — the specific reason (id_jag_issuer_url unset) must
        # not be echoed to unauthenticated callers; it's logged for ops only.
        self.assertEqual(resp.json()["error_description"], "ID-JAG could not be verified")

    def test_rejects_when_id_jag_iss_does_not_match_domain_issuer(self) -> None:
        # The IdP binding is exact-match on the issuer URL — even a sibling IdP
        # that happens to know the same user is rejected unless explicitly bound.
        domain = OrganizationDomain.objects.get(domain=_VERIFIED_DOMAIN)
        config = domain.identity_provider_config
        config.id_jag_issuer_url = "https://idp.example.com"
        config.save()

        assertion = _make_id_jag(issuer="https://other-idp.example.com")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")
        # Uniform response — do not disclose that the IdP issuer is wrong vs.
        # that the domain isn't bound at all.
        self.assertEqual(resp.json()["error_description"], "ID-JAG could not be verified")

    def test_issuer_match_is_slash_normalized(self) -> None:
        # Store the issuer without trailing slash; ID-JAG carries one. The
        # comparison must succeed because we rstrip on both sides — otherwise
        # legitimate IdPs that always include a trailing slash on `iss` would
        # be impossible to bind.
        domain = OrganizationDomain.objects.get(domain=_VERIFIED_DOMAIN)
        config = domain.identity_provider_config
        config.id_jag_issuer_url = _IDP_ISSUER
        config.save()

        assertion = _make_id_jag(issuer=_IDP_ISSUER + "/")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_custom_jwks_url_is_passed_to_jwks_client(self) -> None:
        # When `id_jag_jwks_url` is set on the domain, we skip OIDC discovery and
        # point PyJWKClient at the explicit URL. We assert by inspecting the
        # arguments passed to `_get_jwks_client` rather than reasserting the
        # signature (the mock already returns our test public key).
        domain = OrganizationDomain.objects.get(domain=_VERIFIED_DOMAIN)
        config = domain.identity_provider_config
        config.id_jag_jwks_url = "https://idp.example.com/keys.json"
        config.save()

        # Re-patch to capture call args; the base setUp patch doesn't expose
        # them in a way that survives across multiple tests.
        signing_key = MagicMock()
        signing_key.key = _public_key_for(_IDP_PRIVATE_KEY_PEM)
        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.return_value = signing_key
        with patch("posthog.api.id_jag._get_jwks_client", return_value=mock_jwks_client) as mock_get:
            assertion = _make_id_jag()
            resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs.get("jwks_url"), "https://idp.example.com/keys.json")

    def test_allowed_clients_permits_listed_client_id(self) -> None:
        domain = OrganizationDomain.objects.get(domain=_VERIFIED_DOMAIN)
        config = domain.identity_provider_config
        config.id_jag_allowed_clients = ["client_first", "client_second"]
        config.save()

        assertion = _make_id_jag(client_id="client_second")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_allowed_clients_rejects_unlisted_client_id(self) -> None:
        domain = OrganizationDomain.objects.get(domain=_VERIFIED_DOMAIN)
        config = domain.identity_provider_config
        config.id_jag_allowed_clients = ["client_first", "client_second"]
        config.save()

        assertion = _make_id_jag(client_id="client_third")
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.json()["error"], "invalid_client")

    def test_rejects_missing_resource_claim(self) -> None:
        assertion = jwt.encode(
            {
                "iss": _IDP_ISSUER,
                "sub": "user@example.com",
                "aud": _AUTH_SERVER_URL,
                "client_id": _RESOURCE_CLIENT_ID,
                # resource intentionally missing
                "scope": "feature_flag:read",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
            },
            _IDP_PRIVATE_KEY_PEM,
            algorithm="RS256",
            headers={"typ": ID_JAG_TOKEN_TYPE},
        )
        resp = self._post_token({"grant_type": JWT_BEARER_GRANT_TYPE, "assertion": assertion})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["error"], "invalid_grant")

    def test_get_sub_format(self) -> None:
        self.assertEqual(_get_sub("example.com", "alice@example.com"), "example.com:alice@example.com")

    def test_get_scopes_intersection(self) -> None:
        self.assertEqual(_get_scopes(["a", "b", "c"], ["b", "c", "d"]), ["b", "c"])
        # Order follows the requested list.
        self.assertEqual(_get_scopes(["a", "b", "c"], ["c", "a"]), ["c", "a"])
        # No requested scope means we issue exactly what the ID-JAG authorized.
        self.assertEqual(_get_scopes(["a", "b"], None), ["a", "b"])
        # Empty intersection returns [] (token still issues per spec).
        self.assertEqual(_get_scopes(["a"], ["b"]), [])

    def test_issue_access_token_helper(self) -> None:
        assertion = _make_id_jag()
        token, granted, expires_in = issue_access_token(
            assertion, requested_scope="feature_flag:read", request_client_id=_RESOURCE_CLIENT_ID
        )
        self.assertEqual(granted, ["feature_flag:read"])
        self.assertEqual(expires_in, 300)
        # Token decodable with the AS public key.
        jwt.decode(
            token,
            _public_key_for(_AS_PRIVATE_KEY_PEM),
            algorithms=["RS256"],
            audience=_RESOURCE_URL,
            issuer=_AUTH_SERVER_URL,
        )


@override_settings(
    OIDC_RSA_PRIVATE_KEY=_AS_PRIVATE_KEY_PEM,
    SITE_URL=_SITE_URL,
    ID_JAG_ACCESS_TOKEN_TTL_SECONDS=300,
    ID_JAG_CLOCK_SKEW_SECONDS=30,
)
class TestIDJagAccessTokenAuthentication(APIBaseTest):
    """Resource-server side: verify inbound access tokens authenticate the
    matching user and surface the scope claim for downstream permission checks.
    """

    CONFIG_AUTO_LOGIN = False

    def setUp(self) -> None:
        super().setUp()
        self.user.email = "user@example.com"
        self.user.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.XAA_AUTHENTICATION, "name": "XAA Authentication"}
        ]
        self.organization.save()

    def _mint_access_token(
        self,
        *,
        sub: str | None = None,
        email: str | None = None,
        aud: str = _RESOURCE_URL,
        iss: str = _AUTH_SERVER_URL,
        scope: str = "feature_flag:read",
        client_id: str = _RESOURCE_CLIENT_ID,
        exp_seconds: int = 300,
        typ_header: str = ACCESS_TOKEN_TYPE,
        signing_pem: str | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": iss,
            "sub": sub if sub is not None else f"{_PROVIDER_NAME}:{self.user.email}",
            "email": email if email is not None else self.user.email,
            "aud": aud,
            "client_id": client_id,
            "scope": scope,
            "app_org": _PROVIDER_NAME,
            "org_id": str(self.organization.id),
            "iat": now,
            "exp": now + exp_seconds,
            "jti": f"at-{now}",
        }
        if extra_claims:
            payload.update(extra_claims)
        return jwt.encode(
            payload,
            signing_pem or _AS_PRIVATE_KEY_PEM,
            algorithm="RS256",
            headers={"typ": typ_header},
        )

    def _call_authenticated(self, token: str) -> Any:
        return self.client.get("/api/users/@me/", HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_valid_token_authenticates_user(self) -> None:
        token = self._mint_access_token(scope="user:read")
        resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.json()["email"], self.user.email)

    def test_rejects_when_org_loses_xaa_billing_feature(self) -> None:
        # Entitlement is re-checked on every request, mirroring the membership
        # re-validation: a token minted while the org was entitled must stop
        # authenticating once the XAA billing feature is removed.
        self.organization.available_product_features = []
        self.organization.save()

        token = self._mint_access_token(scope="user:read")
        resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_scope_claim_drives_permission(self) -> None:
        # `user:read` is the scope needed for /api/users/@me/.
        ok = self._mint_access_token(scope="user:read")
        self.assertEqual(self._call_authenticated(ok).status_code, status.HTTP_200_OK)

        # Empty scope → no access at any resource endpoint.
        empty = self._mint_access_token(scope="")
        self.assertEqual(self._call_authenticated(empty).status_code, status.HTTP_403_FORBIDDEN)

        # Wrong scope → permission denied (403).
        wrong = self._mint_access_token(scope="feature_flag:read")
        self.assertEqual(self._call_authenticated(wrong).status_code, status.HTTP_403_FORBIDDEN)

    def test_expired_token_rejected(self) -> None:
        token = self._mint_access_token(exp_seconds=-60, scope="user:read")
        resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_wrong_audience_rejected(self) -> None:
        token = self._mint_access_token(aud="https://different-resource.example.com", scope="user:read")
        resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_wrong_issuer_rejected(self) -> None:
        token = self._mint_access_token(iss="https://attacker.example.com", scope="user:read")
        resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_signature_rejected(self) -> None:
        other_pem = generate_rsa_private_key_pem()
        token = self._mint_access_token(scope="user:read", signing_pem=other_pem)
        resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_signed_with_inactive_key_still_authenticates(self) -> None:
        # Mid-rotation: a token minted under the previous active key keeps working once
        # that key is demoted to inactive and a freshly generated key takes over signing.
        token = self._mint_access_token(scope="user:read", signing_pem=_AS_PRIVATE_KEY_PEM)
        with override_settings(
            OIDC_RSA_PRIVATE_KEY=generate_rsa_private_key_pem(),
            OIDC_RSA_PRIVATE_KEYS_INACTIVE=[_AS_PRIVATE_KEY_PEM],
        ):
            resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.json()["email"], self.user.email)

    def test_token_signed_with_neither_active_nor_inactive_key_rejected(self) -> None:
        token = self._mint_access_token(scope="user:read", signing_pem=generate_rsa_private_key_pem())
        with override_settings(
            OIDC_RSA_PRIVATE_KEY=_AS_PRIVATE_KEY_PEM,
            OIDC_RSA_PRIVATE_KEYS_INACTIVE=[generate_rsa_private_key_pem()],
        ):
            resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_required_claim_rejected(self) -> None:
        # Hand-craft without `scope`
        now = int(time.time())
        payload = {
            "iss": _AUTH_SERVER_URL,
            "sub": f"{_PROVIDER_NAME}:{self.user.email}",
            "aud": _RESOURCE_URL,
            "client_id": _RESOURCE_CLIENT_ID,
            # scope intentionally missing
            "iat": now,
            "exp": now + 300,
        }
        token = jwt.encode(payload, _AS_PRIVATE_KEY_PEM, algorithm="RS256", headers={"typ": ACCESS_TOKEN_TYPE})
        resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unknown_user_email_rejected(self) -> None:
        token = self._mint_access_token(
            sub=f"{_PROVIDER_NAME}:no-such-user@nowhere.example.com",
            email="no-such-user@nowhere.example.com",
            scope="user:read",
        )
        resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_opaque_sub_with_email_claim_authenticates_user(self) -> None:
        # OIDC IdPs (Okta, Auth0, Entra) emit opaque `sub` values — the user's
        # PostHog identity is in the separate `email` claim. The resource-side
        # authenticator must key off `email`, not the userSub half of `sub`.
        token = self._mint_access_token(
            sub=f"{_PROVIDER_NAME}:auth0|opaque-id-abc123",
            email=self.user.email,
            scope="user:read",
        )
        resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.json()["email"], self.user.email)

    def test_missing_email_claim_rejected(self) -> None:
        # `email` is the authenticated identity — a token without it must not
        # fall back to parsing `sub` for an email.
        now = int(time.time())
        payload = {
            "iss": _AUTH_SERVER_URL,
            "sub": f"{_PROVIDER_NAME}:{self.user.email}",
            # email intentionally missing
            "aud": _RESOURCE_URL,
            "client_id": _RESOURCE_CLIENT_ID,
            "scope": "user:read",
            "org_id": str(self.organization.id),
            "iat": now,
            "exp": now + 300,
        }
        token = jwt.encode(payload, _AS_PRIVATE_KEY_PEM, algorithm="RS256", headers={"typ": ACCESS_TOKEN_TYPE})
        resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_malformed_sub_claim_rejected(self) -> None:
        token = self._mint_access_token(sub="no_provider_prefix", scope="user:read")
        resp = self._call_authenticated(token)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_id_jag_jwt_passes_through(self) -> None:
        """A JWT without `typ: at+jwt` must not be claimed by ID-JAG auth — it
        could be e.g. a sharing JWT handled by another backend."""
        now = int(time.time())
        non_id_jag = jwt.encode(
            {"sub": "x", "iat": now, "exp": now + 60},
            _AS_PRIVATE_KEY_PEM,
            algorithm="RS256",
            headers={"typ": "JWT"},
        )
        auth = IDJagAccessTokenAuthentication()
        from unittest.mock import Mock

        req = Mock()
        req.headers = {"authorization": f"Bearer {non_id_jag}"}
        self.assertIsNone(auth.authenticate(req))

    def test_personal_api_key_prefix_passes_through(self) -> None:
        auth = IDJagAccessTokenAuthentication()
        from unittest.mock import Mock

        for prefix in ("phx_abc", "pha_abc", "phs_abc"):
            req = Mock()
            req.headers = {"authorization": f"Bearer {prefix}"}
            self.assertIsNone(auth.authenticate(req))

    def test_no_authorization_header_passes_through(self) -> None:
        auth = IDJagAccessTokenAuthentication()
        from unittest.mock import Mock

        req = Mock()
        req.headers = {}
        self.assertIsNone(auth.authenticate(req))

    def test_routing_mixin_endpoint_authenticates_before_jwt_authentication(self) -> None:
        """Regression test: viewsets that inherit the routing mixin (e.g.
        `/api/projects/@current/`) get a default authenticator chain that
        includes `JwtAuthentication` ahead of other token-based backends.

        `JwtAuthentication.decode_jwt` hard-codes HS256 + the JWT signing key and raises
        `AuthenticationFailed` (→ 401) on any non-`jwt.DecodeError` exception,
        including the `InvalidAlgorithmError` that fires for an RS256 ID-JAG
        access token. If `IDJagAccessTokenAuthentication` doesn't run first,
        valid ID-JAG tokens get a 401 on every routing-mixin-based endpoint
        and never reach the resource server's scope check.

        Hitting `/api/projects/@current/` with a `project:read` ID-JAG token
        must return 200 — not 401.
        """
        token = self._mint_access_token(scope="project:read")
        resp = self.client.get(f"/api/projects/@current/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.content)
        self.assertEqual(resp.json()["id"], self.team.id)
