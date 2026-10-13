from datetime import timedelta

from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized

from posthog.redis import TEST_clear_clients
from posthog.token_bucket import Budget, TEST_reset_scripts

from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, StripeProvisioningTestBase

URL = f"{BASE_PATH}/provisioning/account_requests"


class TestRateLimits(StripeProvisioningTestBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        TEST_clear_clients()
        TEST_reset_scripts()
        self.addCleanup(TEST_clear_clients)
        self.addCleanup(TEST_reset_scripts)

    def _account_request(self) -> dict:
        return {
            "id": "acctreq_throttle",
            "email": self.user.email,
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
            "orchestrator": {"type": "stripe", "stripe": {"account": "acct_test"}},
        }

    def test_account_requests_are_rate_limited(self):
        with patch.dict(
            "ee.partners.stripe.api.provisioning.throttling.BUDGETS",
            {"account_requests": Budget(burst=1, per_hour=1)},
        ):
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

    def test_none_budget_disables_the_limit(self):
        with patch.dict("ee.partners.stripe.api.provisioning.throttling.BUDGETS", {"account_requests": None}):
            assert self._post_signed(URL, data=self._account_request()).status_code == 200
            assert self._post_signed(URL, data=self._account_request()).status_code == 200

    def test_resource_creates_use_status_envelope(self):
        token = self._get_bearer_token()
        with patch.dict(
            "ee.partners.stripe.api.provisioning.throttling.BUDGETS",
            {"resource_creates": Budget(burst=1, per_hour=1)},
        ):
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

    @parameterized.expand(
        [
            (
                "account_requests",
                "typed",
                {
                    "type": "error",
                    "error": {"code": "rate_limited", "message": "Rate limit exceeded. Try again later."},
                },
            ),
            (
                "token",
                "typed",
                {
                    "type": "error",
                    "error": {"code": "rate_limited", "message": "Rate limit exceeded. Try again later."},
                },
            ),
            (
                "resources",
                "status",
                {
                    "status": "error",
                    "id": "",
                    "error": {"code": "rate_limited", "message": "Rate limit exceeded. Try again later."},
                },
            ),
        ]
    )
    def test_global_throttle_rejections_match_the_endpoint_bucket_envelope(self, endpoint, _shape, expected_body):
        # A rejection from DEFAULT_THROTTLE_CLASSES must render the spec shape,
        # not DRF's {"detail": ...}, which this namespace's contract never
        # defines. It must also match what the endpoint's own bucket returns:
        # the token endpoint declares the oauth envelope but owes typed here.
        class RefuseEverything:
            def allow_request(self, request, view):
                return False

            def wait(self):
                return 30

        # Minted before the patch, since it spends the token endpoint.
        token = self._get_bearer_token() if endpoint == "resources" else ""

        with patch(
            "ee.partners.stripe.api.provisioning.views.StripeProvisioningAPIView.get_throttles",
            return_value=[RefuseEverything()],
        ):
            if endpoint == "account_requests":
                res = self._post_signed(URL, data=self._account_request())
            elif endpoint == "token":
                res = self._post_signed(
                    f"{BASE_PATH}/oauth/token",
                    data={"grant_type": "authorization_code", "code": "unused"},
                    content_type="application/x-www-form-urlencoded",
                )
            else:
                res = self._post_signed_with_bearer(
                    f"{BASE_PATH}/provisioning/resources", data={"service_id": "analytics"}, token=token
                )

        assert res.status_code == 429
        assert res.json() == expected_body
        assert res["Retry-After"] == "30"
