from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized

from ee.api.agentic_provisioning.test.base import StripeProvisioningTestBase


class TestSharedPaymentToken(StripeProvisioningTestBase):
    @patch("ee.api.agentic_provisioning.views.requests.post")
    @patch("ee.billing.billing_manager.build_billing_token", return_value="test_billing_token")
    @patch("posthog.cloud_utils.get_cached_instance_license")
    def test_provisioning_calls_billing_with_spt(self, mock_license, mock_build_token, mock_post):
        mock_license.return_value = MagicMock()
        mock_post.return_value = MagicMock(status_code=200)

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

        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        assert "/api/activate/authorize" in call_args[0]
        assert call_kwargs["json"] == {"shared_payment_token": "spt_test_123"}
        assert "Bearer test_billing_token" in call_kwargs["headers"]["Authorization"]

    def test_provisioning_works_without_spt(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"

    def test_provisioning_pay_as_you_go_without_spt_returns_error(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "pay_as_you_go"},
            token=token,
        )
        assert res.status_code == 400
        body = res.json()
        assert body["status"] == "error"
        assert body["error"]["code"] == "requires_payment_credentials"

    @patch("ee.api.agentic_provisioning.views.requests.post")
    def test_provisioning_ignores_invalid_payment_credentials_type(self, mock_post):
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
        mock_post.assert_not_called()

    @parameterized.expand(
        [
            ("billing_inactive", False, 400, "requires_payment_credentials"),
            ("billing_already_active", True, 200, "complete"),
        ]
    )
    @patch("ee.api.agentic_provisioning.views.requests.get")
    @patch("ee.api.agentic_provisioning.views.requests.post")
    @patch("ee.billing.billing_manager.build_billing_token", return_value="test_billing_token")
    @patch("posthog.cloud_utils.get_cached_instance_license")
    def test_provisioning_spt_failure(
        self,
        _name,
        has_active_subscription,
        expected_status,
        expected_code,
        mock_license,
        mock_build_token,
        mock_post,
        mock_get,
    ):
        mock_license.return_value = MagicMock()
        mock_post.return_value = MagicMock(status_code=500)
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: {"customer": {"has_active_subscription": has_active_subscription}}
        )

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
        assert res.status_code == expected_status
        body = res.json()
        if expected_status == 400:
            assert body["error"]["code"] == expected_code
        else:
            assert body["status"] == expected_code

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
