import time

from django.test import override_settings

from parameterized import parameterized

from ee.partners.stripe.api.provisioning.signature import compute_signature
from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, HMAC_SECRET, StripeProvisioningTestBase

HEALTH_URL = f"{BASE_PATH}/provisioning/health"


class TestSignatureVerification(StripeProvisioningTestBase):
    def test_valid_signature_and_version(self):
        res = self._get_signed(HEALTH_URL)
        assert res.status_code == 200
        assert res.json() == {"supported_versions": ["0.1d"], "status": "ok"}

    def test_wrong_secret_rejected(self):
        ts = int(time.time())
        sig = compute_signature("wrong_secret", ts, b"")
        res = self.client.get(HEALTH_URL, HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}", HTTP_API_VERSION="0.1d")
        assert res.status_code == 401
        assert res.json() == {"error": {"code": "invalid_signature", "message": "Signature verification failed"}}

    def test_expired_timestamp_rejected(self):
        stale_ts = int(time.time()) - 600
        res = self.client.get(
            HEALTH_URL, HTTP_STRIPE_SIGNATURE=self._sign_body(b"", timestamp=stale_ts), HTTP_API_VERSION="0.1d"
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "invalid_signature"

    def test_missing_signature_header_rejected(self):
        res = self.client.get(HEALTH_URL, HTTP_API_VERSION="0.1d")
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "invalid_signature"

    def test_dual_signed_header_matches_either_secret(self):
        # During secret rotation the sender includes v1 entries for the old and
        # new secret; verification must pass if any of them matches.
        ts = int(time.time())
        old_sig = compute_signature("retired_secret", ts, b"")
        current_sig = compute_signature(HMAC_SECRET, ts, b"")
        res = self.client.get(
            HEALTH_URL,
            HTTP_STRIPE_SIGNATURE=f"t={ts},v1={old_sig},v1={current_sig}",
            HTTP_API_VERSION="0.1d",
        )
        assert res.status_code == 200

    @override_settings(STRIPE_SIGNING_SECRET="")
    def test_missing_secret_is_server_error(self):
        res = self._get_signed(HEALTH_URL)
        assert res.status_code == 500
        assert res.json()["error"]["code"] == "server_error"

    @parameterized.expand([("missing", None), ("unsupported", "9.9z")])
    def test_bad_api_version_rejected(self, _name, version):
        sig = self._sign_body(b"")
        if version is None:
            res = self.client.get(HEALTH_URL, HTTP_STRIPE_SIGNATURE=sig)
        else:
            res = self.client.get(HEALTH_URL, HTTP_STRIPE_SIGNATURE=sig, HTTP_API_VERSION=version)
        assert res.status_code == 400
        assert res.json() == {"error": {"code": "invalid_api_version", "message": "Supported API-Versions: 0.1d"}}
