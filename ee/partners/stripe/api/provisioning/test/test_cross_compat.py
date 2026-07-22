import time
from datetime import timedelta
from urllib.parse import urlencode

from django.utils import timezone

from ee.partners.stripe.api.provisioning.signature import compute_signature
from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, HMAC_SECRET, StripeProvisioningTestBase

OLD_BASE_PATH = "/api/agentic"


class TestCrossNamespaceCompatibility(StripeProvisioningTestBase):
    """Stripe traffic drains from /api/agentic to /api/partners/stripe gradually,
    so credentials minted on either namespace must stay usable on the other."""

    def _exchange(self, token_url: str, params: dict):
        body = urlencode(params).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)
        return self.client.post(
            token_url,
            data=body,
            content_type="application/x-www-form-urlencoded",
            headers={"stripe-signature": f"t={ts},v1={sig}", "api-version": "0.1d"},
        )

    def _account_request_body(self, email: str) -> dict:
        return {
            "id": "acctreq_compat",
            "email": email,
            "scopes": ["query:read"],
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
            "orchestrator": {"type": "stripe", "stripe": {"account": "acct_compat"}},
        }

    def test_code_minted_on_old_namespace_redeems_on_new_token_endpoint(self):
        res = self._post_signed(
            f"{OLD_BASE_PATH}/provisioning/account_requests", data=self._account_request_body(self.user.email)
        )
        assert res.status_code == 200
        code = res.json()["oauth"]["code"]

        res = self._exchange(f"{BASE_PATH}/oauth/token", {"grant_type": "authorization_code", "code": code})
        assert res.status_code == 200
        assert res.json()["access_token"].startswith("pha_")

    def test_code_minted_on_new_namespace_redeems_on_old_token_endpoint(self):
        res = self._post_signed(
            f"{BASE_PATH}/provisioning/account_requests", data=self._account_request_body(self.user.email)
        )
        assert res.status_code == 200
        code = res.json()["oauth"]["code"]

        res = self._exchange(f"{OLD_BASE_PATH}/oauth/token", {"grant_type": "authorization_code", "code": code})
        assert res.status_code == 200
        assert res.json()["access_token"].startswith("pha_")

    def test_refresh_token_from_old_endpoint_rotates_on_new_endpoint(self):
        res = self._post_signed(
            f"{OLD_BASE_PATH}/provisioning/account_requests", data=self._account_request_body(self.user.email)
        )
        code = res.json()["oauth"]["code"]
        old_tokens = self._exchange(
            f"{OLD_BASE_PATH}/oauth/token", {"grant_type": "authorization_code", "code": code}
        ).json()

        res = self._exchange(
            f"{BASE_PATH}/oauth/token", {"grant_type": "refresh_token", "refresh_token": old_tokens["refresh_token"]}
        )
        assert res.status_code == 200
        assert res.json()["access_token"] != old_tokens["access_token"]

    def test_bearer_from_old_endpoint_works_on_new_resource_endpoints(self):
        res = self._post_signed(
            f"{OLD_BASE_PATH}/provisioning/account_requests", data=self._account_request_body(self.user.email)
        )
        code = res.json()["oauth"]["code"]
        access_token = self._exchange(
            f"{OLD_BASE_PATH}/oauth/token", {"grant_type": "authorization_code", "code": code}
        ).json()["access_token"]

        res = self._get_signed_with_bearer(f"{BASE_PATH}/provisioning/resources/{self.team.id}", token=access_token)
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
