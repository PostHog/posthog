import json
import time
from ipaddress import ip_address

from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized

from posthog.api.oauth.cimd import CIMDFetchError
from posthog.api.oauth.client_assertion import CLIENT_ASSERTION_TYPE_JWT_BEARER, ClientAssertionError
from posthog.models.oauth import OAuthApplication

from ee.api.agentic_provisioning.test.base import TEST_PARTNER_SCOPES, ProvisioningTestBase, provisioning_config

REGISTRATION_URL = "/api/agentic/provisioning/client_registration"
ACCOUNT_REQUESTS_URL = "/api/agentic/provisioning/account_requests"
CIMD_URL = "https://newpartner.example.com/.well-known/oauth-client-metadata.json"
JWKS_URI = "https://newpartner.example.com/.well-known/jwks.json"
KID = "reg-key"

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


class _CacheHeaderlessResponse:
    """Stands in for the requests.Response the CIMD fetch returns, which is read only for
    cache headers."""

    headers: dict[str, str] = {}


@override_settings(SITE_URL="https://us.posthog.com")
class TestClientRegistration(ProvisioningTestBase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def _register(self, body: dict, *, jwks: dict | None = None, metadata_error: Exception | None = None):
        """Drive the endpoint with both outbound fetches stubbed. They are separate patches
        because the metadata document and the JWKS are fetched by different modules."""
        metadata = {
            "client_id": CIMD_URL,
            "client_name": "New Partner",
            "redirect_uris": ["https://newpartner.example.com/callback"],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "private_key_jwt",
            "jwks_uri": JWKS_URI,
        }
        metadata_patch = (
            patch(
                "posthog.api.oauth.cimd.fetch_client_json_document",
                side_effect=metadata_error,
            )
            if metadata_error
            else patch(
                "posthog.api.oauth.cimd.fetch_client_json_document",
                return_value=(metadata, _CacheHeaderlessResponse()),
            )
        )
        with (
            # example.com does not resolve, and the SSRF guard runs before the fetch, so
            # without this the metadata check would fail for a reason unrelated to the test.
            patch("posthog.security.url_validation.resolve_host_ips", return_value={ip_address("93.184.216.34")}),
            metadata_patch,
            patch(
                "posthog.api.oauth.client_assertion.fetch_client_json_document",
                return_value=(jwks if jwks is not None else _jwks(), None),
            ),
        ):
            return self._post_api(REGISTRATION_URL, body)

    def _make_partner(self, **overrides) -> OAuthApplication:
        defaults = {
            "name": "Registered Partner",
            "client_id": "opaque-registered-client-id",
            "is_cimd_client": True,
            "cimd_metadata_url": CIMD_URL,
            "client_secret": "",
            "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
            "jwks_uri": JWKS_URI,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": "https://newpartner.example.com/callback",
            "algorithm": "RS256",
            "scopes": TEST_PARTNER_SCOPES,
            "is_provisioning_partner": True,
            # The default here is a client that registered itself: it does ordinary
            # provisioning, and holds none of the capabilities an admin has to grant.
            "_provisioning_config": provisioning_config(
                active=True,
                can_create_accounts=True,
                can_use_github_grants=False,
                can_start_wizard_runs=False,
            ),
        }
        return OAuthApplication.objects.create(**{**defaults, **overrides})

    def _assertion(self, **overrides) -> str:
        now = int(time.time())
        claims = {
            "iss": CIMD_URL,
            "sub": CIMD_URL,
            "aud": "https://us.posthog.com/api/agentic/oauth/token",
            "jti": f"reg-jti-{now}",
            "iat": now,
            "exp": now + 60,
        }
        claims.update(overrides)
        return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": KID})

    def test_unregistered_client_id_is_reported_as_not_registered(self):
        res = self._register({"client_id": "totally-unknown-client-id"})

        assert res.status_code == 400
        body = res.json()
        assert body["registered"] is False
        assert body["error"]["code"] == "registration_failed"
        # The per-check detail is the point: a bare error code would not tell the partner
        # whether the document was unreachable, malformed, or simply never registered.
        assert [check["name"] for check in body["checks"]] == ["client_exists"]
        assert body["checks"][0]["ok"] is False

    def test_reports_diagnostics_for_a_private_key_jwt_partner(self):
        self._make_partner()

        res = self._register({"client_id": CIMD_URL})

        assert res.status_code == 200, res.json()
        body = res.json()
        assert body["registered"] is True
        assert body["client_id"] == CIMD_URL
        assert body["token_endpoint_auth_method"] == "private_key_jwt"
        # Signing assertions with a key it published itself proves only that it controls its
        # own metadata document, which anyone can do, so it is not yet a partner PostHog
        # vouched for.
        assert body["capabilities"]["github_grants"] is False
        checks = {check["name"]: check for check in body["checks"]}
        assert checks["jwks"]["ok"] is True
        assert KID in checks["jwks"]["detail"]

    def test_partner_registered_by_an_admin_can_use_github_grants(self):
        self._make_partner(_provisioning_config=provisioning_config(can_use_github_grants=True))

        res = self._register({"client_id": CIMD_URL})

        assert res.status_code == 200, res.json()
        assert res.json()["capabilities"]["github_grants"] is True

    def test_public_client_is_told_it_cannot_use_github_grants(self):
        self._make_partner(client_type=OAuthApplication.CLIENT_PUBLIC, jwks_uri=None)

        # A document declaring no auth method keeps the refresh from re-promoting it.
        res = self._register({"client_id": CIMD_URL}, metadata_error=CIMDFetchError("offline"))

        assert res.status_code == 200, res.json()
        body = res.json()
        assert body["token_endpoint_auth_method"] == "none"
        # The reason a public client gets 403 on the grant endpoints is not derivable from its
        # own metadata document, so the diagnostics have to state it.
        assert body["capabilities"]["github_grants"] is False

    def test_opts_an_existing_cimd_oauth_app_into_provisioning(self):
        # A CIMD app registered through the ordinary OAuth flow carries no provisioning
        # config. Opting it in used to happen implicitly on the auth path; it is now this
        # endpoint's job, and without it such a client could never reach any endpoint here.
        self._make_partner(is_provisioning_partner=False, _provisioning_config=provisioning_config(active=False))

        res = self._register({"client_id": CIMD_URL})

        assert res.status_code == 200, res.json()
        app = OAuthApplication.objects.get(cimd_metadata_url=CIMD_URL)
        assert app.is_provisioning_partner
        assert app.provisioning.active

    def test_deactivated_partner_is_not_reactivated_by_re_registering(self):
        # Only a client that is not yet a partner gets the defaults applied. Registering again
        # must not undo an admin turning a partner off, which would make the endpoint a way for
        # a partner to reinstate itself.
        self._make_partner(_provisioning_config=provisioning_config(active=False))

        res = self._register({"client_id": CIMD_URL})

        assert res.status_code == 400, res.json()
        assert res.json()["error"]["code"] == "registration_failed"
        app = OAuthApplication.objects.get(cimd_metadata_url=CIMD_URL)
        assert app.provisioning.active is False

    def test_unreachable_jwks_is_reported_as_a_failed_check(self):
        self._make_partner()

        with patch(
            "posthog.api.oauth.client_assertion._fetch_jwks_document",
            side_effect=ClientAssertionError("Client keys could not be retrieved"),
        ):
            res = self._register({"client_id": CIMD_URL})

        # Registration itself is fine, the keys are not: reporting both separately is what
        # lets a partner tell "PostHog doesn't know me" from "my key server is down".
        assert res.status_code == 200, res.json()
        checks = {check["name"]: check for check in res.json()["checks"]}
        assert checks["metadata_document"]["ok"] is True
        assert checks["provisioning_enabled"]["ok"] is True
        assert checks["jwks"]["ok"] is False

    @parameterized.expand(
        [
            ("valid", {}, True),
            ("wrong_audience", {"aud": "https://elsewhere.example.com/token"}, False),
            ("wrong_subject", {"sub": "https://attacker.example.com/doc.json"}, False),
        ]
    )
    def test_verifies_a_supplied_assertion(self, _name, overrides, expected_ok):
        self._make_partner()

        res = self._register(
            {
                "client_id": CIMD_URL,
                "client_assertion": self._assertion(**overrides),
                "client_assertion_type": CLIENT_ASSERTION_TYPE_JWT_BEARER,
            }
        )

        assert res.status_code == 200, res.json()
        checks = {check["name"]: check for check in res.json()["checks"]}
        assert checks["client_assertion"]["ok"] is expected_ok

    def test_rejects_an_assertion_with_the_wrong_type(self):
        self._make_partner()

        res = self._register(
            {"client_id": CIMD_URL, "client_assertion": "x.y.z", "client_assertion_type": "urn:something:else"}
        )

        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_request"


class TestUnregisteredClientsFailClosed(ProvisioningTestBase):
    """Every endpoint requires an already-registered client and points at the registration
    endpoint, instead of the old behavior where an unknown CIMD client_id silently kicked off
    a background registration and answered "retry shortly"."""

    @parameterized.expand(
        [
            ("account_requests", ACCOUNT_REQUESTS_URL, {"id": "r1", "email": "nobody@example.com"}),
            ("github_grants", "/api/agentic/provisioning/github/grants", {"code": "gh-code"}),
        ]
    )
    def test_unknown_client_id_is_pointed_at_the_registration_endpoint(self, _name, url, body):
        res = self._post_api(url, {**body, "client_id": CIMD_URL})

        assert res.status_code == 401
        message = res.json()["error"]["message"]
        assert "No provisioning client is registered" in message
        assert "client_registration" in message
