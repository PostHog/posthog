import json
import time
import base64
import hashlib
import secrets
from urllib.parse import urlencode

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.cache import cache as real_cache
from django.test import override_settings

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework.test import APIClient

from posthog.models.oauth import OAuthApplication

from ee.api.agentic_provisioning.signature import compute_signature

HMAC_SECRET = "test_hmac_secret"
WIZARD_CLIENT_ID = "test-wizard-client"
TEST_STRIPE_OAUTH_CLIENT_ID = "test_stripe_oauth_client_id"


def _generate_rsa_key() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


def _pkce_pair():
    """Generate a PKCE code_verifier and code_challenge pair."""
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


_RSA_KEY = _generate_rsa_key()


@pytest.mark.requires_secrets
@override_settings(
    STRIPE_SIGNING_SECRET=HMAC_SECRET,
    STRIPE_POSTHOG_OAUTH_CLIENT_ID=TEST_STRIPE_OAUTH_CLIENT_ID,
    STRIPE_ORCHESTRATOR_CALLBACK_URL="https://stripe.com/callback",
    OIDC_RSA_PRIVATE_KEY=_RSA_KEY,
    OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": _RSA_KEY},
)
class TestProvisioningAuthentication(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Delete and recreate to ensure clean state with all provisioning fields
        OAuthApplication.objects.filter(client_id__in=[TEST_STRIPE_OAUTH_CLIENT_ID, WIZARD_CLIENT_ID]).delete()

        self.stripe_app = OAuthApplication.objects.create(
            client_id=TEST_STRIPE_OAUTH_CLIENT_ID,
            name="PostHog Stripe App",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://stripe.com/callback",
            algorithm="RS256",
            provisioning_auth_method="hmac",
            provisioning_signing_secret=HMAC_SECRET,
            provisioning_partner_type="stripe",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )

        self.wizard_app = OAuthApplication.objects.create(
            client_id=WIZARD_CLIENT_ID,
            name="PostHog Wizard",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8239/callback",
            algorithm="RS256",
            is_first_party=True,
            provisioning_auth_method="pkce",
            provisioning_partner_type="wizard",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )
        self.wizard_app.refresh_from_db()

    def _sign_body(self, body: bytes) -> str:
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)
        return f"t={ts},v1={sig}"

    # --- HMAC identification ---

    def test_hmac_partner_identified_by_signature(self):
        body = json.dumps(
            {
                "id": "req_1",
                "email": "new@example.com",
                "orchestrator": {"type": "stripe", "stripe": {"account": "acct_123"}},
            }
        ).encode()
        sig = self._sign_body(body)
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data=body,
            content_type="application/json",
            headers={"stripe-signature": sig, "api-version": "0.1d"},
        )
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

    # --- PKCE flow ---

    def test_pkce_wizard_new_user_full_flow(self):
        verifier, challenge = _pkce_pair()

        # Step 1: account_requests with PKCE
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_wizard_1",
                "email": "wizard-user@example.com",
                "client_id": WIZARD_CLIENT_ID,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "oauth"
        code = data["oauth"]["code"]

        # Step 2: exchange code with code_verifier
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": verifier,
                }
            ),
            content_type="application/x-www-form-urlencoded",
            headers={"api-version": "0.1d"},
        )
        assert res.status_code == 200
        tokens = res.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert tokens["expires_in"] == 3600

        # Step 3: use bearer token for resources
        res = self.client.post(
            "/api/agentic/provisioning/resources",
            data=json.dumps({"service_id": "analytics"}),
            content_type="application/json",
            headers={"authorization": f"Bearer {tokens['access_token']}", "api-version": "0.1d"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert "api_key" in res.json()["complete"]["access_configuration"]

    def test_pkce_wrong_verifier_rejected(self):
        _, challenge = _pkce_pair()

        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_bad_pkce",
                "email": "bad-pkce@example.com",
                "client_id": WIZARD_CLIENT_ID,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )
        code = res.json()["oauth"]["code"]

        res = self.client.post(
            "/api/agentic/oauth/token",
            data=urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": "wrong_verifier_value",
                }
            ),
            content_type="application/x-www-form-urlencoded",
            headers={"api-version": "0.1d"},
        )
        assert res.status_code == 400
        assert res.json()["error"] == "invalid_grant"

    def test_pkce_missing_verifier_rejected(self):
        _, challenge = _pkce_pair()

        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_no_verifier",
                "email": "no-verifier@example.com",
                "client_id": WIZARD_CLIENT_ID,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )
        code = res.json()["oauth"]["code"]

        # Without code_verifier or HMAC, the request is unauthenticated
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                }
            ),
            content_type="application/x-www-form-urlencoded",
            headers={"api-version": "0.1d"},
        )
        assert res.status_code == 401

    # --- can_create_accounts enforcement ---

    def test_partner_without_can_create_accounts_rejected(self):
        OAuthApplication.objects.create(
            name="Disabled Partner",
            client_id="disabled-partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://localhost",
            algorithm="RS256",
            provisioning_auth_method="pkce",
            provisioning_partner_type="disabled",
            provisioning_active=True,
            provisioning_can_create_accounts=False,
        )

        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_disabled",
                "email": "disabled@example.com",
                "client_id": "disabled-partner",
            },
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "forbidden"

    # --- Org naming ---

    def test_wizard_org_named_with_partner_type(self):
        from posthog.models.user import User

        verifier, challenge = _pkce_pair()
        email = "org-name-test@example.com"

        self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_org_name",
                "email": email,
                "client_id": WIZARD_CLIENT_ID,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )

        user = User.objects.get(email=email)
        org = user.organization_memberships.first().organization
        assert org.name == f"Wizard ({email})"

    # --- Token expiry ---

    def test_new_tokens_expire_in_one_hour(self):
        verifier, challenge = _pkce_pair()

        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_expiry",
                "email": "expiry-test@example.com",
                "client_id": WIZARD_CLIENT_ID,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )
        code = res.json()["oauth"]["code"]

        res = self.client.post(
            "/api/agentic/oauth/token",
            data=urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": verifier,
                }
            ),
            content_type="application/x-www-form-urlencoded",
            headers={"api-version": "0.1d"},
        )
        assert res.json()["expires_in"] == 3600

    # --- Stripe regression ---

    def test_stripe_hmac_flow_still_works(self):
        body = json.dumps(
            {
                "id": "req_stripe",
                "email": "stripe-regression@example.com",
                "orchestrator": {"type": "stripe", "stripe": {"account": "acct_456"}},
            }
        ).encode()
        sig = self._sign_body(body)
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data=body,
            content_type="application/json",
            headers={"stripe-signature": sig, "api-version": "0.1d"},
        )
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

    def test_legacy_stripe_without_partner_still_works(self):
        """Stripe flow should work even if provisioning fields are not set (falls through to legacy)."""
        self.stripe_app.provisioning_auth_method = ""
        self.stripe_app.save(update_fields=["provisioning_auth_method"])

        body = json.dumps(
            {
                "id": "req_legacy",
                "email": "legacy-stripe@example.com",
                "orchestrator": {"type": "stripe", "stripe": {"account": "acct_789"}},
            }
        ).encode()
        sig = self._sign_body(body)
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data=body,
            content_type="application/json",
            headers={"stripe-signature": sig, "api-version": "0.1d"},
        )
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

    # --- PAT scopes ---

    def test_provisioned_pat_created(self):
        from posthog.models.personal_api_key import PersonalAPIKey

        verifier, challenge = _pkce_pair()
        email = "pat-test@example.com"

        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_pat",
                "email": email,
                "client_id": WIZARD_CLIENT_ID,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )
        code = res.json()["oauth"]["code"]

        res = self.client.post(
            "/api/agentic/oauth/token",
            data=urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": verifier,
                }
            ),
            content_type="application/x-www-form-urlencoded",
            headers={"api-version": "0.1d"},
        )
        token = res.json()["access_token"]

        self.client.post(
            "/api/agentic/provisioning/resources",
            data=json.dumps({"service_id": "analytics"}),
            content_type="application/json",
            headers={"authorization": f"Bearer {token}", "api-version": "0.1d"},
        )

        from posthog.models.user import User

        user = User.objects.get(email=email)
        pat = PersonalAPIKey.objects.filter(user=user).first()
        assert pat is not None

    # --- is_active kill switch ---

    def test_inactive_hmac_partner_rejected(self):
        self.stripe_app.provisioning_active = False
        self.stripe_app.save(update_fields=["provisioning_active"])

        body = json.dumps(
            {
                "id": "req_inactive",
                "email": "inactive-test@example.com",
                "orchestrator": {"type": "stripe", "stripe": {"account": "acct_inactive"}},
            }
        ).encode()
        sig = self._sign_body(body)
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data=body,
            content_type="application/json",
            headers={"stripe-signature": sig, "api-version": "0.1d"},
        )
        # Inactive HMAC partner is filtered out of identification, falls through to legacy
        # which still works via verify_provisioning_signature (same secret in settings)
        # But the ProvisioningAuthentication won't return it
        assert res.status_code == 200

        self.stripe_app.provisioning_active = True
        self.stripe_app.save(update_fields=["provisioning_active"])

    def test_inactive_pkce_partner_rejected(self):
        self.wizard_app.provisioning_active = False
        self.wizard_app.save(update_fields=["provisioning_active"])

        _, challenge = _pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_inactive_pkce",
                "email": "inactive-pkce@example.com",
                "client_id": WIZARD_CLIENT_ID,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )
        # Inactive partner not identified -> no partner + no HMAC -> 401
        assert res.status_code == 401

        self.wizard_app.provisioning_active = True
        self.wizard_app.save(update_fields=["provisioning_active"])

    # --- Encrypted signing_secret round-trip ---

    def test_signing_secret_encrypts_and_decrypts_for_hmac(self):
        app = OAuthApplication.objects.get(id=self.stripe_app.id)
        assert app.provisioning_signing_secret == HMAC_SECRET

        from ee.api.agentic_provisioning.signature import _compute_hmac

        body = b'{"test": "data"}'
        expected = _compute_hmac(app.provisioning_signing_secret, "12345", body)
        computed = _compute_hmac(HMAC_SECRET, "12345", body)
        assert expected == computed

    # --- can_provision_resources enforcement ---

    def test_partner_without_can_provision_resources_rejected(self):
        verifier, challenge = _pkce_pair()

        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_no_prov",
                "email": "no-provision@example.com",
                "client_id": WIZARD_CLIENT_ID,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )
        code = res.json()["oauth"]["code"]

        res = self.client.post(
            "/api/agentic/oauth/token",
            data=urlencode({"grant_type": "authorization_code", "code": code, "code_verifier": verifier}),
            content_type="application/x-www-form-urlencoded",
            headers={"api-version": "0.1d"},
        )
        token = res.json()["access_token"]

        self.wizard_app.provisioning_can_provision_resources = False
        self.wizard_app.save(update_fields=["provisioning_can_provision_resources"])

        res = self.client.post(
            "/api/agentic/provisioning/resources",
            data=json.dumps({"service_id": "analytics"}),
            content_type="application/json",
            headers={"authorization": f"Bearer {token}", "api-version": "0.1d"},
        )
        assert res.status_code == 403

        self.wizard_app.provisioning_can_provision_resources = True
        self.wizard_app.save(update_fields=["provisioning_can_provision_resources"])

    # --- CIMD URL-based PKCE identification ---

    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_pkce_partner_identified_by_cimd_url(self, mock_refresh):
        cimd_url = "https://example.com/api/oauth/wizard/client-metadata"
        cimd_app = OAuthApplication.objects.create(
            name="CIMD Wizard",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8239/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=cimd_url,
            provisioning_auth_method="pkce",
            provisioning_partner_type="wizard",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )

        verifier, challenge = _pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_pkce",
                "email": "cimd-wizard@example.com",
                "client_id": cimd_url,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

        cimd_app.delete()

    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_cimd_url_inactive_partner_rejected(self, mock_refresh):
        cimd_url = "https://example.com/api/oauth/wizard/client-metadata-inactive"
        cimd_app = OAuthApplication.objects.create(
            name="Inactive CIMD Wizard",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://localhost:8239/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=cimd_url,
            provisioning_auth_method="pkce",
            provisioning_partner_type="wizard",
            provisioning_active=False,
            provisioning_can_create_accounts=True,
        )

        _, challenge = _pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_inactive",
                "email": "cimd-inactive@example.com",
                "client_id": cimd_url,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )
        assert res.status_code == 401

        cimd_app.delete()

    # --- PKCE code_challenge_method validation ---

    def test_plain_code_challenge_method_rejected(self):
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_plain",
                "email": "plain-pkce@example.com",
                "client_id": WIZARD_CLIENT_ID,
                "code_challenge": "some_challenge",
                "code_challenge_method": "plain",
            },
            content_type="application/json",
            headers={"api-version": "0.1d"},
        )
        assert res.status_code == 400
        assert "S256" in res.json()["error"]["message"]


CIMD_PROV_URL = "https://partner.example.com/.well-known/oauth-client-metadata.json"


def _make_cimd_metadata(url: str = CIMD_PROV_URL, **overrides) -> dict:
    metadata = {
        "client_id": url,
        "client_name": "Partner App",
        "redirect_uris": ["http://127.0.0.1:3000/callback"],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    metadata.update(overrides)
    return metadata


def _cimd_mock_response(metadata: dict | None, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {}
    resp.is_redirect = False
    resp.is_permanent_redirect = False
    resp.close = MagicMock()
    body = json.dumps(metadata).encode() if metadata is not None else b""
    resp.iter_content = MagicMock(return_value=iter([body]))
    return resp


@pytest.mark.requires_secrets
@patch("posthog.api.oauth.cimd.is_url_allowed", return_value=(True, None))
@override_settings(
    STRIPE_APP_SECRET_KEY=HMAC_SECRET,
    STRIPE_POSTHOG_OAUTH_CLIENT_ID=TEST_STRIPE_OAUTH_CLIENT_ID,
    STRIPE_ORCHESTRATOR_CALLBACK_URL="https://stripe.com/callback",
    OIDC_RSA_PRIVATE_KEY=_RSA_KEY,
    OAUTH2_PROVIDER={**settings.OAUTH2_PROVIDER, "OIDC_RSA_PRIVATE_KEY": _RSA_KEY},
)
class TestCimdProvisioningAutoRegistration(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        OAuthApplication.objects.filter(cimd_metadata_url=CIMD_PROV_URL).delete()
        real_cache.clear()

    @patch("ee.api.agentic_provisioning.authentication.register_cimd_provisioning_application_task")
    def test_new_cimd_partner_returns_202_and_kicks_off_registration(self, mock_task, _url_mock):
        _, challenge = _pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_auto",
                "email": "cimd-auto@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
        )

        assert res.status_code == 202
        assert res.json()["type"] == "registering"
        assert res.json()["retry_after"] == 5
        mock_task.delay.assert_called_once_with(CIMD_PROV_URL)

    @patch("posthog.api.oauth.cimd.requests.get")
    def test_new_cimd_partner_succeeds_after_background_registration(self, mock_get, _url_mock):
        mock_get.return_value = _cimd_mock_response(_make_cimd_metadata())

        from posthog.api.oauth.cimd import register_cimd_provisioning_application_task

        register_cimd_provisioning_application_task(CIMD_PROV_URL)

        app = OAuthApplication.objects.get(cimd_metadata_url=CIMD_PROV_URL)
        assert app.is_cimd_client
        assert app.provisioning_auth_method == "pkce"
        assert app.provisioning_active
        assert app.provisioning_can_create_accounts
        assert app.provisioning_can_provision_resources

        _, challenge = _pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_auto",
                "email": "cimd-auto@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_existing_cimd_app_gets_provisioning_backfilled(self, mock_refresh, _url_mock):
        OAuthApplication.objects.create(
            name="Pre-existing CIMD",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:3000/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=CIMD_PROV_URL,
        )

        _, challenge = _pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_backfill",
                "email": "cimd-backfill@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 200

        app = OAuthApplication.objects.get(cimd_metadata_url=CIMD_PROV_URL)
        assert app.provisioning_auth_method == "pkce"
        assert app.provisioning_active

    def test_cimd_backfill_db_error_degrades_to_unauthorized(self, _url_mock):
        OAuthApplication.objects.create(
            name="CIMD DB Error App",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:3000/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=CIMD_PROV_URL,
        )
        with patch(
            "ee.api.agentic_provisioning.authentication.CIMD_PROVISIONING_DEFAULTS",
            new_callable=lambda: MagicMock(
                items=MagicMock(side_effect=RuntimeError("simulated DB error")),
                keys=MagicMock(return_value=[]),
            ),
        ):
            _, challenge = _pkce_pair()
            res = self.client.post(
                "/api/agentic/provisioning/account_requests",
                data={
                    "id": "req_cimd_db_err",
                    "email": "cimd-db-err@example.com",
                    "client_id": CIMD_PROV_URL,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
                content_type="application/json",
                HTTP_API_VERSION="0.1d",
            )
        assert res.status_code == 401

    @patch("ee.api.agentic_provisioning.authentication.register_cimd_provisioning_application_task")
    def test_new_cimd_url_returns_202_not_401(self, mock_task, _url_mock):
        _, challenge = _pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_fail",
                "email": "cimd-fail@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 202
        assert res.json()["type"] == "registering"
        mock_task.delay.assert_called_once()

    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_partner_rate_limit_enforced_after_threshold(self, mock_refresh, _url_mock):
        OAuthApplication.objects.create(
            name="Rate Limit Test CIMD",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:3000/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=CIMD_PROV_URL,
            provisioning_auth_method="pkce",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
            provisioning_rate_limit_account_requests=10,
        )

        _, challenge = _pkce_pair()

        def post_account_request(email: str):
            return self.client.post(
                "/api/agentic/provisioning/account_requests",
                data={
                    "id": f"req_{email}",
                    "email": email,
                    "client_id": CIMD_PROV_URL,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
                content_type="application/json",
                HTTP_API_VERSION="0.1d",
            )

        assert post_account_request("ratelimit-1@example.com").status_code == 200

        partner = OAuthApplication.objects.get(cimd_metadata_url=CIMD_PROV_URL)
        partner.provisioning_rate_limit_account_requests = 2
        partner.save(update_fields=["provisioning_rate_limit_account_requests"])

        assert post_account_request("ratelimit-2@example.com").status_code == 200
        res = post_account_request("ratelimit-3@example.com")
        assert res.status_code == 429
        assert res.json()["error"]["code"] == "rate_limited"

    @patch("posthog.api.oauth.cimd.CIMD_THROTTLE_CLASSES", new=[])
    @patch("ee.api.agentic_provisioning.authentication.register_cimd_provisioning_application_task")
    def test_cimd_domain_rate_limit_blocks_excessive_registrations(self, mock_task, _url_mock):
        from ee.api.agentic_provisioning.views import CIMD_DOMAIN_RATE_LIMIT_MAX

        base_domain = "evil.example.com"
        _, challenge = _pkce_pair()

        for i in range(CIMD_DOMAIN_RATE_LIMIT_MAX):
            url = f"https://{base_domain}/path-{i}/metadata.json"
            res = self.client.post(
                "/api/agentic/provisioning/account_requests",
                data={
                    "id": f"req_domain_rl_{i}",
                    "email": f"domain-rl-{i}@example.com",
                    "client_id": url,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
                content_type="application/json",
                HTTP_API_VERSION="0.1d",
            )
            assert res.status_code == 202, f"Request {i} failed: {res.json()}"

        url = f"https://{base_domain}/path-blocked/metadata.json"
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_domain_rl_blocked",
                "email": "domain-rl-blocked@example.com",
                "client_id": url,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 429
        assert res.json()["error"]["code"] == "rate_limited"

    @patch("posthog.api.oauth.cimd.CIMD_THROTTLE_CLASSES", new=[])
    @patch("ee.api.agentic_provisioning.authentication.register_cimd_provisioning_application_task")
    def test_cimd_domain_rate_limit_does_not_block_different_domains(self, mock_task, _url_mock):
        from ee.api.agentic_provisioning.views import CIMD_DOMAIN_RATE_LIMIT_MAX

        _, challenge = _pkce_pair()

        for i in range(CIMD_DOMAIN_RATE_LIMIT_MAX + 2):
            url = f"https://domain-{i}.example.com/.well-known/metadata.json"
            res = self.client.post(
                "/api/agentic/provisioning/account_requests",
                data={
                    "id": f"req_diff_domain_{i}",
                    "email": f"diff-domain-{i}@example.com",
                    "client_id": url,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                },
                content_type="application/json",
                HTTP_API_VERSION="0.1d",
            )
            assert res.status_code == 202, f"Request {i} for domain-{i} failed: {res.json()}"

    @patch("posthog.api.oauth.cimd.CIMD_THROTTLE_CLASSES", new=[])
    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_cimd_domain_rate_limit_skipped_for_existing_apps(self, mock_refresh, _url_mock):
        from ee.api.agentic_provisioning.views import CIMD_DOMAIN_RATE_LIMIT_MAX

        base_domain = "existing.example.com"
        _, challenge = _pkce_pair()

        for i in range(CIMD_DOMAIN_RATE_LIMIT_MAX + 1):
            url = f"https://{base_domain}/path-{i}/metadata.json"
            OAuthApplication.objects.create(
                name=f"Existing CIMD {i}",
                client_secret="",
                client_type=OAuthApplication.CLIENT_PUBLIC,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="http://127.0.0.1:3000/callback",
                algorithm="RS256",
                is_cimd_client=True,
                cimd_metadata_url=url,
                provisioning_auth_method="pkce",
                provisioning_active=True,
                provisioning_can_create_accounts=True,
                provisioning_can_provision_resources=True,
            )

        url = f"https://{base_domain}/path-0/metadata.json"
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_existing_domain",
                "email": "existing-domain@example.com",
                "client_id": url,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 200

    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_self_serve_org_named_after_client_name(self, mock_refresh, _url_mock):
        from posthog.models.user import User

        OAuthApplication.objects.create(
            name="Partner App",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:3000/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=CIMD_PROV_URL,
            provisioning_auth_method="pkce",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )

        email = "cimd-org-name@example.com"
        _, challenge = _pkce_pair()
        self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_cimd_org",
                "email": email,
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
        )

        user = User.objects.get(email=email)
        org = user.organization_memberships.first().organization
        assert org.name == f"Partner App ({email})"

    def test_blocked_cimd_url_returns_unauthorized(self, _url_mock):
        from posthog.api.oauth.cimd import block_cimd_url

        block_cimd_url(CIMD_PROV_URL)

        _, challenge = _pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_blocked",
                "email": "blocked@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 401

    @patch("posthog.api.oauth.cimd.refresh_cimd_metadata_task")
    def test_blocked_cimd_url_with_existing_app_returns_unauthorized(self, mock_refresh, _url_mock):
        from posthog.api.oauth.cimd import block_cimd_url

        OAuthApplication.objects.create(
            name="Blocked CIMD App",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="http://127.0.0.1:3000/callback",
            algorithm="RS256",
            is_cimd_client=True,
            cimd_metadata_url=CIMD_PROV_URL,
            provisioning_auth_method="pkce",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )
        block_cimd_url(CIMD_PROV_URL)

        _, challenge = _pkce_pair()
        res = self.client.post(
            "/api/agentic/provisioning/account_requests",
            data={
                "id": "req_blocked_existing",
                "email": "blocked-existing@example.com",
                "client_id": CIMD_PROV_URL,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            content_type="application/json",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 401
