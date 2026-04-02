import time

from unittest.mock import patch

from django.test import override_settings

from ee.api.agentic_provisioning.signature import compute_signature
from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestProvisioningHealth(StripeProvisioningTestBase):
    def test_valid_request(self):
        res = self._get_signed("/api/agentic/provisioning/health")
        assert res.status_code == 200
        data = res.json()
        assert data["supported_versions"] == ["0.1d"]
        assert data["status"] == "ok"

    def test_missing_signature_returns_401(self):
        res = self.client.get("/api/agentic/provisioning/health", HTTP_API_VERSION="0.1d")
        assert res.status_code == 401

    def test_invalid_signature_returns_401(self):
        res = self.client.get(
            "/api/agentic/provisioning/health",
            HTTP_STRIPE_SIGNATURE=f"t={int(time.time())},v1={'00' * 32}",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 401

    def test_missing_api_version_returns_400(self):
        sig = self._sign_body(b"")
        res = self.client.get("/api/agentic/provisioning/health", HTTP_STRIPE_SIGNATURE=sig)
        assert res.status_code == 400

    def test_wrong_api_version_returns_400(self):
        sig = self._sign_body(b"")
        res = self.client.get(
            "/api/agentic/provisioning/health",
            HTTP_STRIPE_SIGNATURE=sig,
            HTTP_API_VERSION="1.0",
        )
        assert res.status_code == 400

    def test_expired_timestamp_returns_401(self):
        old_ts = int(time.time()) - 600
        sig = compute_signature(HMAC_SECRET, old_ts, b"")
        res = self.client.get(
            "/api/agentic/provisioning/health",
            HTTP_STRIPE_SIGNATURE=f"t={old_ts},v1={sig}",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 401

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_signature_succeeds_with_rate_limiting_enabled(self, _mock):
        res = self._get_signed("/api/agentic/provisioning/health")
        assert res.status_code == 200

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_post_signature_succeeds_with_rate_limiting_enabled(self, _mock):
        res = self._post_signed(
            "/api/agentic/provisioning/account-requests",
            data={"email": "test@example.com", "account_name": "Test"},
        )
        assert res.status_code not in (400, 500), f"Unexpected error: {res.json()}"
