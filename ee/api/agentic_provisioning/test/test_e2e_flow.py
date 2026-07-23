from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from django.utils import timezone

from posthog.models.oauth import OAuthApplication
from posthog.models.user import User

from ee.api.agentic_provisioning.test.base import ProvisioningTestBase

TOKEN_URL = "/api/agentic/oauth/token"


class TestE2EProvisioningFlow(ProvisioningTestBase):
    """Walk through the full partner provisioning flow end-to-end."""

    def test_full_provisioning_flow(self):
        partner_token = self._get_bearer_token()

        # 1. Account request (new user) from the bearer-authenticated partner
        verifier, challenge = self._pkce_pair()
        account_request = {
            "id": "acctreq_e2e_test",
            "email": "e2e-test@example.com",
            "scopes": ["query:read", "project:read"],
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
        }
        res = self._post_with_bearer(
            "/api/agentic/provisioning/account_requests", data=account_request, token=partner_token
        )
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"
        auth_code = res.json()["oauth"]["code"]

        # 2. Exchange authorization code for tokens (PKCE)
        res = self._post_api(
            TOKEN_URL, {"grant_type": "authorization_code", "code": auth_code, "code_verifier": verifier}
        )
        assert res.status_code == 200
        token_data = res.json()
        assert token_data["token_type"] == "bearer"
        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        assert access_token.startswith("pha_")
        assert refresh_token.startswith("phr_")
        assert token_data["account"]["id"]

        # 3. Provision a resource
        res = self._post_with_bearer("/api/agentic/provisioning/resources", data={}, token=access_token)
        assert res.status_code == 200
        resource_data = res.json()
        assert resource_data["status"] == "complete"
        resource_id = resource_data["id"]
        assert "api_key" in resource_data["complete"]["access_configuration"]

        # 4. Get resource status
        res = self._get_with_bearer(f"/api/agentic/provisioning/resources/{resource_id}", token=access_token)
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert res.json()["id"] == resource_id

        # 5. Rotate credentials (generates a new api_token)
        original_api_key = resource_data["complete"]["access_configuration"]["api_key"]
        res = self._post_with_bearer(
            f"/api/agentic/provisioning/resources/{resource_id}/rotate_credentials", token=access_token
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert res.json()["id"] == resource_id
        rotated_api_key = res.json()["complete"]["access_configuration"]["api_key"]
        assert rotated_api_key != original_api_key

        # 6. Deep link — create and use it to login
        res = self._post_with_bearer(
            "/api/agentic/provisioning/deep_links", data={"purpose": "dashboard"}, token=access_token
        )
        assert res.status_code == 200
        deep_link_url = res.json()["url"]
        assert "expires_at" in res.json()
        deep_link_token = parse_qs(urlparse(deep_link_url).query)["token"][0]

        # In prod the user verifies the email via the welcome reset link (which flips
        # is_email_verified=True) before any deep-link login works. Simulate that here.
        provisioned_user = User.objects.get(email="e2e-test@example.com")
        provisioned_user.is_email_verified = True
        provisioned_user.save(update_fields=["is_email_verified"])

        login_res = self.client.get(f"/agentic/login?token={deep_link_token}")
        assert login_res.status_code == 302
        assert "/project/" in login_res["Location"]

        me_res = self.client.get("/api/users/@me/")
        assert me_res.status_code == 200
        assert me_res.json()["email"] == "e2e-test@example.com"

        reuse_res = self.client.get(f"/agentic/login?token={deep_link_token}")
        assert reuse_res.status_code == 302
        assert "expired_or_invalid_token" in reuse_res["Location"]

        # 7. Refresh the token
        res = self._post_api(TOKEN_URL, {"grant_type": "refresh_token", "refresh_token": refresh_token})
        assert res.status_code == 200
        new_access_token = res.json()["access_token"]
        assert new_access_token != access_token
        assert new_access_token.startswith("pha_")

        # 8. New token works; the rotated-out one no longer does
        res = self._get_with_bearer(f"/api/agentic/provisioning/resources/{resource_id}", token=new_access_token)
        assert res.status_code == 200
        assert res.json()["status"] == "complete"

        res = self._get_with_bearer(f"/api/agentic/provisioning/resources/{resource_id}", token=access_token)
        assert res.status_code == 401

    def test_pkce_existing_user_consent_e2e(self):
        """E2E: PKCE partner with existing user goes through browser consent flow."""
        OAuthApplication.objects.create(
            client_id="pkce-e2e-partner",
            name="PKCE E2E Partner",
            client_secret="",
            client_type=OAuthApplication.CLIENT_PUBLIC,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://partner.example.com/callback",
            algorithm="RS256",
            is_first_party=True,
            scopes=["query:read"],
            provisioning_auth_method="pkce",
            provisioning_partner_type="test_partner",
            provisioning_active=True,
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
        )

        existing_user = User.objects.create_and_join(
            organization=self.organization,
            email="consent-e2e@example.com",
            password="testpass",
            first_name="Consent",
        )

        # 1. Partner calls account_requests - gets requires_auth (not a direct code)
        verifier, challenge = self._pkce_pair()
        account_request = {
            "id": "acctreq_consent_e2e",
            "email": "consent-e2e@example.com",
            "scopes": ["query:read"],
            "client_id": "pkce-e2e-partner",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
        }
        res = self._post_api("/api/agentic/provisioning/account_requests", account_request)
        assert res.status_code == 200
        data = res.json()
        assert data["type"] == "requires_auth"
        auth_url = data["requires_auth"]["url"]
        assert "/api/agentic/authorize" in auth_url

        # 2. User logs in and visits the authorize URL
        self.client.force_login(existing_user)
        res = self.client.get(auth_url)

        # PKCE partners always go to the consent page, even for single-org/team
        assert res.status_code == 302
        redirect_url = res["Location"]
        assert "/agentic/authorize?" in redirect_url
        consent_state = parse_qs(urlparse(redirect_url).query)["state"][0]

        # 3. User approves on the consent page (simulated via agentic_authorize_confirm)
        res = self._post_api("/api/agentic/authorize/confirm/", {"state": consent_state, "team_id": self.team.id})
        assert res.status_code == 200
        callback_redirect = res.json()["redirect_url"]
        parsed_callback = urlparse(callback_redirect)
        assert parsed_callback.netloc == "partner.example.com"
        auth_code = parse_qs(parsed_callback.query)["code"][0]

        # 4. Partner exchanges auth code for tokens using PKCE
        res = self._post_api(
            TOKEN_URL, {"grant_type": "authorization_code", "code": auth_code, "code_verifier": verifier}
        )
        assert res.status_code == 200
        token_data = res.json()
        assert token_data["token_type"] == "bearer"
        access_token = token_data["access_token"]
        assert access_token.startswith("pha_")

        # 5. Partner provisions a resource with the token
        res = self._post_with_bearer("/api/agentic/provisioning/resources", data={}, token=access_token)
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert "api_key" in res.json()["complete"]["access_configuration"]
