import json
import time
from ipaddress import ip_address

from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from parameterized import parameterized

from posthog.api.oauth.cimd import CIMDFetchError, apply_provisioning_defaults
from posthog.api.oauth.client_assertion import CLIENT_ASSERTION_TYPE_JWT_BEARER, ClientAssertionError
from posthog.models.oauth import OAuthApplication

from ee.api.agentic_provisioning.test.base import TEST_PARTNER_SCOPES, ProvisioningTestBase, provisioning_config

REGISTRATION_URL = "/api/agentic/provisioning/client_registration"
ACCOUNT_REQUESTS_URL = "/api/agentic/provisioning/account_requests"
CIMD_URL = "https://newpartner.example.com/.well-known/oauth-client-metadata.json"
JWKS_URI = "https://newpartner.example.com/.well-known/jwks.json"
KID = "reg-key"

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

_DECLARES_PROVISIONING = {"provisioning": True}


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

    def _document(self, *, com_posthog: object = _DECLARES_PROVISIONING) -> dict:
        """The document a client wanting to register publishes. Passing com_posthog=None leaves
        the namespace out, which is the shape of a third party that never asked for any of
        this."""
        document: dict[str, object] = {
            "client_id": CIMD_URL,
            "client_name": "New Partner",
            "redirect_uris": ["https://newpartner.example.com/callback"],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "private_key_jwt",
            "jwks_uri": JWKS_URI,
        }
        if com_posthog is not None:
            document["com.posthog"] = com_posthog
        return document

    def _register(
        self,
        body: dict,
        *,
        document: dict | None = None,
        jwks: dict | None = None,
        metadata_error: Exception | None = None,
    ):
        """Drive the endpoint with both outbound fetches stubbed. They are separate patches
        because the metadata document and the JWKS are fetched by different modules."""
        metadata = document if document is not None else self._document()
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
            "client_id": CIMD_URL,
            "is_cimd_client": True,
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

    def test_brand_new_partner_is_confidential_on_its_first_registration(self):
        # No pre-existing row: this is the client_id's first ever contact with PostHog, so the
        # promotion has to happen inline with _create_cimd_application, not wait for the next
        # hourly refresh to notice is_provisioning_partner has since flipped.
        assert not OAuthApplication.objects.filter(client_id=CIMD_URL).exists()

        res = self._register({"client_id": CIMD_URL})

        assert res.status_code == 200, res.json()
        body = res.json()
        assert body["registered"] is True
        assert body["token_endpoint_auth_method"] == "private_key_jwt"
        app = OAuthApplication.objects.get(client_id=CIMD_URL)
        assert app.client_type == OAuthApplication.CLIENT_CONFIDENTIAL
        assert app.is_provisioning_partner

    def test_partner_enablement_and_confidential_promotion_land_together(self):
        # A partner that is enabled while still public would accept the bare-client_id path,
        # so an unauthenticated caller could act as that partner until the promotion landed.
        # apply_provisioning_defaults therefore has to write both in one go, which this pins by
        # calling it directly: splitting the promotion back out leaves this app public.
        app = self._make_partner(
            is_provisioning_partner=False,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            jwks_uri=JWKS_URI,
            _provisioning_config=provisioning_config(active=False, can_create_accounts=False),
        )

        apply_provisioning_defaults(app)

        app.refresh_from_db()
        assert app.is_provisioning_partner
        assert app.client_type == OAuthApplication.CLIENT_CONFIDENTIAL

    def test_kill_switched_client_is_not_promoted_to_confidential(self):
        # An admin can disable a client before it ever becomes a partner. The kill switch stops
        # apply_provisioning_defaults from enabling the partner, and the promotion rides on that
        # same write, so the client stays public rather than ending up confidential with a
        # self-declared jwks_uri and no partner status behind it.
        self._make_partner(
            is_provisioning_partner=False,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            jwks_uri=None,
            _provisioning_config=provisioning_config(disabled=True, active=False, can_create_accounts=False),
        )

        self._register({"client_id": CIMD_URL})

        app = OAuthApplication.objects.get(client_id=CIMD_URL)
        assert app.client_type == OAuthApplication.CLIENT_PUBLIC
        assert app.is_provisioning_partner is False

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
        app = OAuthApplication.objects.get(client_id=CIMD_URL)
        assert app.is_provisioning_partner
        assert app.provisioning.active

    @parameterized.expand(
        [
            ("no_com_posthog_namespace", None),
            ("declares_false", {"provisioning": False}),
            # A truthy string is a malformed declaration, not consent: reading it as one would
            # grant a stranger the capabilities off someone else's typo.
            ("declares_a_truthy_string", {"provisioning": "true"}),
        ]
    )
    def test_a_document_that_does_not_opt_in_is_not_promoted(self, _name, com_posthog):
        # A CIMD client_id is a public URL, so anyone can name a third party's OAuth client
        # here. Promoting it would hand the caller that client's identity and account-request
        # quota, and flip the client's own token exchanges onto private_key_jwt, which its
        # runtime may never send.
        self._make_partner(
            is_provisioning_partner=False,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            jwks_uri=None,
            _provisioning_config=provisioning_config(active=False, can_create_accounts=False),
        )

        res = self._register({"client_id": CIMD_URL}, document=self._document(com_posthog=com_posthog))

        assert res.status_code == 400, res.json()
        checks = {check["name"]: check for check in res.json()["checks"]}
        assert checks["provisioning_enabled"]["ok"] is False
        assert '"com.posthog": {"provisioning": true}' in checks["provisioning_enabled"]["detail"]
        app = OAuthApplication.objects.get(client_id=CIMD_URL)
        assert app.is_provisioning_partner is False
        assert app.provisioning.can_create_accounts is False
        assert app.client_type == OAuthApplication.CLIENT_PUBLIC

    def test_a_document_we_could_not_store_is_not_promoted(self):
        # A rejected save leaves the row describing the previous document. Promoting off it
        # would grant provisioning, and derive client_type from a stored key set, that the
        # client's current document does not describe, while the response called the fetch fine.
        self._make_partner(
            is_provisioning_partner=False,
            client_type=OAuthApplication.CLIENT_PUBLIC,
            jwks_uri=None,
            _provisioning_config=provisioning_config(active=False, can_create_accounts=False),
        )
        document = self._document()
        # Passes CIMD document validation, which does not look at fragments, and is refused by
        # the model.
        document["redirect_uris"] = ["https://newpartner.example.com/callback#fragment"]

        res = self._register({"client_id": CIMD_URL}, document=document)

        assert res.status_code == 400, res.json()
        checks = {check["name"]: check for check in res.json()["checks"]}
        assert checks["metadata_document"]["ok"] is False
        assert "fragment not allowed" in checks["metadata_document"]["detail"]
        # The opt-in may well be in the document we refused, so the answer points at the
        # rejection rather than sending the client's owner after a key they already published.
        assert '"com.posthog"' not in checks["provisioning_enabled"]["detail"]
        assert "metadata_document" in checks["provisioning_enabled"]["detail"]
        app = OAuthApplication.objects.get(client_id=CIMD_URL)
        assert app.is_provisioning_partner is False
        assert app.provisioning.can_create_accounts is False
        assert app.client_type == OAuthApplication.CLIENT_PUBLIC
        assert app.redirect_uris == "https://newpartner.example.com/callback"

    def test_deactivated_partner_is_not_reactivated_by_re_registering(self):
        # Only a client that is not yet a partner gets the defaults applied. Registering again
        # must not undo an admin turning a partner off, which would make the endpoint a way for
        # a partner to reinstate itself.
        self._make_partner(_provisioning_config=provisioning_config(active=False))

        res = self._register({"client_id": CIMD_URL})

        assert res.status_code == 400, res.json()
        assert res.json()["error"]["code"] == "registration_failed"
        app = OAuthApplication.objects.get(client_id=CIMD_URL)
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
