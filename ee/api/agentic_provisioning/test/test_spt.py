from django.core.cache import cache

from ee.api.agentic_provisioning.test.base import StripeProvisioningTestBase
from ee.api.agentic_provisioning.views import get_shared_payment_token


class TestSharedPaymentToken(StripeProvisioningTestBase):
    def test_provisioning_stores_spt_when_provided(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={
                "service_id": "analytics",
                "payment_credentials": {
                    "type": "stripe_payment_token",
                    "stripe_payment_token": "spt_test_123",
                },
            },
            token=token,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"

        stored = get_shared_payment_token(str(self.organization.id))
        assert stored == "spt_test_123"

    def test_provisioning_works_without_spt(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"

        stored = get_shared_payment_token(str(self.organization.id))
        assert stored is None

    def test_provisioning_ignores_invalid_payment_credentials_type(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={
                "service_id": "analytics",
                "payment_credentials": {
                    "type": "unknown_type",
                    "token": "abc",
                },
            },
            token=token,
        )
        assert res.status_code == 200

        stored = get_shared_payment_token(str(self.organization.id))
        assert stored is None

    def test_spt_overwrites_previous_value(self):
        token = self._get_bearer_token()

        self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={
                "service_id": "analytics",
                "payment_credentials": {
                    "type": "stripe_payment_token",
                    "stripe_payment_token": "spt_first",
                },
            },
            token=token,
        )
        assert get_shared_payment_token(str(self.organization.id)) == "spt_first"

        # Provision again with a new SPT (e.g. plan upgrade)
        token2 = self._get_bearer_token()
        self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={
                "service_id": "analytics",
                "payment_credentials": {
                    "type": "stripe_payment_token",
                    "stripe_payment_token": "spt_second",
                },
            },
            token=token2,
        )
        assert get_shared_payment_token(str(self.organization.id)) == "spt_second"

    def test_token_exchange_returns_orchestrator(self):
        """Token exchange should return payment_credentials: orchestrator so Stripe collects payment."""
        token_response = self._exchange_code_and_get_response()
        assert token_response["account"]["payment_credentials"] == "orchestrator"

    def _exchange_code_and_get_response(self) -> dict:
        import time
        from urllib.parse import urlencode

        from ee.api.agentic_provisioning.signature import compute_signature
        from ee.api.agentic_provisioning.test.base import HMAC_SECRET
        from ee.api.agentic_provisioning.views import AUTH_CODE_CACHE_PREFIX

        code = f"test_code_spt_{id(self)}"
        cache.set(
            f"{AUTH_CODE_CACHE_PREFIX}{code}",
            {
                "user_id": self.user.id,
                "org_id": str(self.organization.id),
                "team_id": self.team.id,
                "stripe_account_id": "acct_123",
                "scopes": ["query:read"],
                "region": "US",
            },
            timeout=300,
        )
        body = urlencode({"grant_type": "authorization_code", "code": code}).encode()
        ts = int(time.time())
        sig = compute_signature(HMAC_SECRET, ts, body)
        res = self.client.post(
            "/api/agentic/oauth/token",
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
        )
        return res.json()
