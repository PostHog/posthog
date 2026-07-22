import time
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlparse

from django.utils import timezone

from posthog.models.user import User

from ee.partners.stripe.api.provisioning.signature import compute_signature
from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, HMAC_SECRET, StripeProvisioningTestBase


class TestE2EProvisioningFlow(StripeProvisioningTestBase):
    def _exchange(self, params: dict):
        body = urlencode(params).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)
        return self.client.post(
            f"{BASE_PATH}/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            headers={"stripe-signature": f"t={ts},v1={sig}", "api-version": "0.1d"},
        )

    def test_full_provisioning_flow(self):
        # 1. Health check
        res = self._get_signed(f"{BASE_PATH}/provisioning/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        # 2. List services (billing not available in tests, falls back to the static catalog)
        res = self._get_signed(f"{BASE_PATH}/provisioning/services")
        assert res.status_code == 200
        assert {service["id"] for service in res.json()["data"]} == {"free", "pay_as_you_go", "analytics"}

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
        res = self._post_signed(f"{BASE_PATH}/provisioning/account_requests", data=account_request)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"
        auth_code = res.json()["oauth"]["code"]

        # 4. Exchange authorization code for tokens
        res = self._exchange({"grant_type": "authorization_code", "code": auth_code})
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
            f"{BASE_PATH}/provisioning/resources",
            data={"service_id": "analytics"},
            token=access_token,
        )
        assert res.status_code == 200
        resource_data = res.json()
        assert resource_data["status"] == "complete"
        resource_id = resource_data["id"]
        assert "api_key" in resource_data["complete"]["access_configuration"]

        # 6. Get resource status
        res = self._get_signed_with_bearer(f"{BASE_PATH}/provisioning/resources/{resource_id}", token=access_token)
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert res.json()["id"] == resource_id

        # 7. Rotate credentials (generates a new api_token)
        original_api_key = resource_data["complete"]["access_configuration"]["api_key"]
        res = self._post_signed_with_bearer(
            f"{BASE_PATH}/provisioning/resources/{resource_id}/rotate_credentials", token=access_token
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        rotated_api_key = res.json()["complete"]["access_configuration"]["api_key"]
        assert rotated_api_key != original_api_key

        # 8. Update the service
        res = self._post_signed_with_bearer(
            f"{BASE_PATH}/provisioning/resources/{resource_id}/update_service",
            data={"service_id": "free"},
            token=access_token,
        )
        assert res.status_code == 200
        assert res.json()["service_id"] == "free"

        # 9. Deep link - create and use it to login (consumed by /api/partners/stripe/login)
        res = self._post_signed_with_bearer(
            f"{BASE_PATH}/provisioning/deep_links", data={"purpose": "dashboard"}, token=access_token
        )
        assert res.status_code == 200
        deep_link_url = res.json()["url"]
        deep_link_token = parse_qs(urlparse(deep_link_url).query)["token"][0]

        # In prod the user verifies the email via the welcome reset link (which flips
        # is_email_verified=True) before any deep-link login works. Simulate that here.
        provisioned_user = User.objects.get(email="e2e-test@example.com")
        provisioned_user.is_email_verified = True
        provisioned_user.save(update_fields=["is_email_verified"])

        login_res = self.client.get(f"/api/partners/stripe/login?token={deep_link_token}")
        assert login_res.status_code == 302
        assert "/project/" in login_res["Location"]

        me_res = self.client.get("/api/users/@me/")
        assert me_res.status_code == 200
        assert me_res.json()["email"] == "e2e-test@example.com"

        reuse_res = self.client.get(f"/api/partners/stripe/login?token={deep_link_token}")
        assert reuse_res.status_code == 302
        assert "expired_or_invalid_token" in reuse_res["Location"]

        # 10. Refresh the token
        res = self._exchange({"grant_type": "refresh_token", "refresh_token": refresh_token})
        assert res.status_code == 200
        new_access_token = res.json()["access_token"]
        assert new_access_token != access_token
        assert new_access_token.startswith("pha_")

        # 11. New token works; the rotated-out one no longer does
        res = self._get_signed_with_bearer(f"{BASE_PATH}/provisioning/resources/{resource_id}", token=new_access_token)
        assert res.status_code == 200
        res = self._get_signed_with_bearer(f"{BASE_PATH}/provisioning/resources/{resource_id}", token=access_token)
        assert res.status_code == 401

    def test_existing_user_provisioning_flow(self):
        User.objects.create_and_join(
            organization=self.organization,
            email="existing-e2e@example.com",
            password="testpass",
            first_name="Existing",
        )

        account_request = {
            "id": "acctreq_existing_e2e",
            "email": "existing-e2e@example.com",
            "scopes": ["query:read", "project:read"],
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
            "orchestrator": {"type": "stripe", "stripe": {"account": "acct_e2e_existing"}},
        }
        res = self._post_signed(f"{BASE_PATH}/provisioning/account_requests", data=account_request)
        assert res.status_code == 200
        assert res.json()["type"] == "oauth"

        res = self._exchange({"grant_type": "authorization_code", "code": res.json()["oauth"]["code"]})
        assert res.status_code == 200
        token_data = res.json()
        access_token = token_data["access_token"]
        assert len(token_data["account"]["available_teams"]) >= 1

        res = self._post_signed_with_bearer(
            f"{BASE_PATH}/provisioning/resources", data={"service_id": "analytics"}, token=access_token
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert "api_key" in res.json()["complete"]["access_configuration"]
