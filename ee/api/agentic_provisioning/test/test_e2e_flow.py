import time
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlparse

from django.test import override_settings
from django.utils import timezone

from posthog.models.user import User

from ee.api.agentic_provisioning.signature import compute_signature
from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestE2EProvisioningFlow(StripeProvisioningTestBase):
    """Walk through the full APP 0.1d provisioning flow end-to-end."""

    def test_full_provisioning_flow(self):
        # 1. Health check
        res = self._get_signed("/api/agentic/provisioning/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        # 2. List services (billing not available in tests, returns empty)
        res = self._get_signed("/api/agentic/provisioning/services")
        assert res.status_code == 200

        # 3. Account request (new user)
        account_request = {
            "id": "acctreq_e2e_test",
            "object": "account_request",
            "email": "e2e-test@example.com",
            "scopes": ["query:read", "project:read"],
            "client_capabilities": ["browser"],
            "confirmation_secret": "cs_e2e_secret",
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
            "orchestrator": {
                "type": "stripe",
                "stripe": {
                    "organisation": "org_e2e",
                    "account": "acct_e2e",
                },
            },
        }
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=account_request)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"
        auth_code = res.json()["oauth"]["code"]

        # 4. Exchange authorization code for tokens
        token_body = urlencode({"grant_type": "authorization_code", "code": auth_code}).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, token_body)
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=token_body,
            content_type="application/x-www-form-urlencoded",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 200
        token_data = res.json()
        assert token_data["token_type"] == "bearer"
        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        assert access_token.startswith("pha_")
        assert refresh_token.startswith("phr_")
        assert token_data["account"]["id"]

        # 5. Provision a resource
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=access_token,
        )
        assert res.status_code == 200
        resource_data = res.json()
        assert resource_data["status"] == "complete"
        resource_id = resource_data["id"]
        assert "api_key" in resource_data["complete"]["access_configuration"]

        # 6. Get resource status
        res = self._get_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{resource_id}",
            token=access_token,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert res.json()["id"] == resource_id

        # 7. Rotate credentials (generates a new api_token)
        original_api_key = resource_data["complete"]["access_configuration"]["api_key"]
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{resource_id}/rotate_credentials",
            token=access_token,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert res.json()["id"] == resource_id
        rotated_api_key = res.json()["complete"]["access_configuration"]["api_key"]
        assert rotated_api_key != original_api_key

        # 8. Deep link — create and use it to login
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/deep_links",
            data={"purpose": "dashboard"},
            token=access_token,
        )
        assert res.status_code == 200
        deep_link_url = res.json()["url"]
        assert "expires_at" in res.json()

        parsed = urlparse(deep_link_url)
        deep_link_token = parse_qs(parsed.query)["token"][0]

        login_res = self.client.get(f"/agentic/login?token={deep_link_token}")
        assert login_res.status_code == 302
        assert "/project/" in login_res["Location"]

        me_res = self.client.get("/api/users/@me/")
        assert me_res.status_code == 200
        assert me_res.json()["email"] == "e2e-test@example.com"

        reuse_res = self.client.get(f"/agentic/login?token={deep_link_token}")
        assert reuse_res.status_code == 302
        assert "expired_or_invalid_token" in reuse_res["Location"]

        # 9. Refresh the token
        refresh_body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, refresh_body)
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=refresh_body,
            content_type="application/x-www-form-urlencoded",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 200
        new_access_token = res.json()["access_token"]
        assert new_access_token != access_token
        assert new_access_token.startswith("pha_")

        # 10. Verify new token works on resource endpoint
        res = self._get_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{resource_id}",
            token=new_access_token,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"

        # 11. Old token should no longer work (it was deleted during refresh)
        res = self._get_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{resource_id}",
            token=access_token,
        )
        assert res.status_code == 401

    def test_existing_user_provisioning_flow(self):
        """E2E: existing user gets linked via email without browser redirect."""
        User.objects.create_and_join(
            organization=self.organization,
            email="existing-e2e@example.com",
            password="testpass",
            first_name="Existing",
        )

        # 1. Account request for existing user — should return oauth directly
        account_request = {
            "id": "acctreq_existing_e2e",
            "object": "account_request",
            "email": "existing-e2e@example.com",
            "scopes": ["query:read", "project:read"],
            "client_capabilities": ["browser"],
            "confirmation_secret": "cs_existing_secret",
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
            "orchestrator": {
                "type": "stripe",
                "stripe": {
                    "organisation": "org_e2e",
                    "account": "acct_e2e_existing",
                },
            },
        }
        res = self._post_signed("/api/agentic/provisioning/account_requests", data=account_request)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"
        auth_code = res.json()["oauth"]["code"]

        # 2. Exchange authorization code for tokens
        token_body = urlencode({"grant_type": "authorization_code", "code": auth_code}).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, token_body)
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=token_body,
            content_type="application/x-www-form-urlencoded",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 200
        token_data = res.json()
        access_token = token_data["access_token"]
        assert access_token.startswith("pha_")
        assert "available_teams" in token_data["account"]
        assert len(token_data["account"]["available_teams"]) >= 1

        # 3. Provision a resource
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=access_token,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert "api_key" in res.json()["complete"]["access_configuration"]
