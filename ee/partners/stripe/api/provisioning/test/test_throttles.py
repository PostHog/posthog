from datetime import timedelta

from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, StripeProvisioningTestBase

URL = f"{BASE_PATH}/provisioning/account_requests"


class TestRateLimits(StripeProvisioningTestBase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def _account_request(self) -> dict:
        return {
            "id": "acctreq_throttle",
            "email": self.user.email,
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
            "orchestrator": {"type": "stripe", "stripe": {"account": "acct_test"}},
        }

    def test_account_requests_are_rate_limited(self):
        with patch.dict("ee.partners.stripe.api.provisioning.throttling.RATE_LIMIT_DEFAULTS", {"account_requests": 1}):
            assert self._post_signed(URL, data=self._account_request()).status_code == 200
            res = self._post_signed(URL, data=self._account_request())
        assert res.status_code == 429
        assert res.json() == {
            "type": "error",
            "error": {
                "code": "rate_limited",
                "message": "Rate limit exceeded (account_requests). Try again later.",
            },
        }
        assert int(res["Retry-After"]) > 0

    def test_zero_default_disables_the_limit(self):
        with patch.dict("ee.partners.stripe.api.provisioning.throttling.RATE_LIMIT_DEFAULTS", {"account_requests": 0}):
            assert self._post_signed(URL, data=self._account_request()).status_code == 200
            assert self._post_signed(URL, data=self._account_request()).status_code == 200

    def test_resource_creates_use_status_envelope(self):
        token = self._get_bearer_token()
        with patch.dict("ee.partners.stripe.api.provisioning.throttling.RATE_LIMIT_DEFAULTS", {"resource_creates": 1}):
            first = self._post_signed_with_bearer(
                f"{BASE_PATH}/provisioning/resources", data={"service_id": "analytics"}, token=token
            )
            assert first.status_code == 200
            res = self._post_signed_with_bearer(
                f"{BASE_PATH}/provisioning/resources", data={"service_id": "analytics"}, token=token
            )
        assert res.status_code == 429
        assert res.json() == {
            "status": "error",
            "id": "",
            "error": {
                "code": "rate_limited",
                "message": "Rate limit exceeded. Try again later.",
            },
        }
        assert int(res["Retry-After"]) > 0
