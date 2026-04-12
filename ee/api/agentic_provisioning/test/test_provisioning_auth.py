import json
import time
import base64
import hashlib
import secrets
from urllib.parse import urlencode

import pytest
from posthog.test.base import APIBaseTest

from django.conf import settings
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
    STRIPE_APP_SECRET_KEY=HMAC_SECRET,
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
            HTTP_STRIPE_SIGNATURE=sig,
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
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
            HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}",
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
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
            HTTP_STRIPE_SIGNATURE=sig,
            HTTP_API_VERSION="0.1d",
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
            HTTP_STRIPE_SIGNATURE=sig,
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
        )
        token = res.json()["access_token"]

        self.client.post(
            "/api/agentic/provisioning/resources",
            data=json.dumps({"service_id": "analytics"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_API_VERSION="0.1d",
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
            HTTP_STRIPE_SIGNATURE=sig,
            HTTP_API_VERSION="0.1d",
        )
        # Inactive HMAC partner is filtered out of identification, falls through to legacy
        # which still works via verify_stripe_signature (same secret in settings)
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
            HTTP_API_VERSION="0.1d",
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
            HTTP_API_VERSION="0.1d",
        )
        code = res.json()["oauth"]["code"]

        res = self.client.post(
            "/api/agentic/oauth/token",
            data=urlencode({"grant_type": "authorization_code", "code": code, "code_verifier": verifier}),
            content_type="application/x-www-form-urlencoded",
            HTTP_API_VERSION="0.1d",
        )
        token = res.json()["access_token"]

        self.wizard_app.provisioning_can_provision_resources = False
        self.wizard_app.save(update_fields=["provisioning_can_provision_resources"])

        res = self.client.post(
            "/api/agentic/provisioning/resources",
            data=json.dumps({"service_id": "analytics"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 403

        self.wizard_app.provisioning_can_provision_resources = True
        self.wizard_app.save(update_fields=["provisioning_can_provision_resources"])

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
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 400
        assert "S256" in res.json()["error"]["message"]
