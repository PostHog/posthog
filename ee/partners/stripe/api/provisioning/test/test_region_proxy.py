import json
from datetime import timedelta

from unittest.mock import MagicMock, patch

from django.utils import timezone

from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, StripeProvisioningTestBase


def _fake_upstream(payload: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.content = json.dumps(payload).encode()
    response.json.return_value = payload
    return response


class TestRegionProxy(StripeProvisioningTestBase):
    def _account_request(self, region: str) -> dict:
        return {
            "id": "acctreq_proxy",
            "email": "proxy@example.com",
            "expires_at": (timezone.now() + timedelta(minutes=10)).isoformat(),
            "configuration": {"region": region},
            "orchestrator": {"type": "stripe", "stripe": {"account": "acct_test"}},
        }

    def test_mismatched_body_region_is_proxied_with_path_preserved(self):
        with (
            patch("ee.partners.stripe.api.provisioning.region_proxy.get_instance_region", return_value="US"),
            patch(
                "ee.partners.stripe.api.provisioning.region_proxy.requests.request",
                return_value=_fake_upstream({"type": "oauth", "oauth": {"code": "eu_code"}}),
            ) as proxied,
        ):
            res = self._post_signed(f"{BASE_PATH}/provisioning/account_requests", data=self._account_request("EU"))

        assert res.status_code == 200
        assert res.json() == {"type": "oauth", "oauth": {"code": "eu_code"}}
        target_url = proxied.call_args.kwargs["url"]
        assert target_url == f"http://eu.posthog.com{BASE_PATH}/provisioning/account_requests"
        assert proxied.call_args.kwargs["headers"]["X-PostHog-Proxied"] == "1"

    def test_matching_region_is_served_locally(self):
        with (
            patch("ee.partners.stripe.api.provisioning.region_proxy.get_instance_region", return_value="US"),
            patch("ee.partners.stripe.api.provisioning.region_proxy.requests.request") as proxied,
        ):
            res = self._post_signed(f"{BASE_PATH}/provisioning/account_requests", data=self._account_request("US"))
        assert res.status_code == 200
        proxied.assert_not_called()

    def test_proxy_loop_header_forces_local_handling(self):
        with (
            patch("ee.partners.stripe.api.provisioning.region_proxy.get_instance_region", return_value="US"),
            patch("ee.partners.stripe.api.provisioning.region_proxy.requests.request") as proxied,
        ):
            res = self._post_signed(
                f"{BASE_PATH}/provisioning/account_requests",
                data=self._account_request("EU"),
                HTTP_X_POSTHOG_PROXIED="1",
            )
        assert res.status_code == 200
        proxied.assert_not_called()

    def test_unknown_bearer_is_proxied(self):
        with (
            patch("ee.partners.stripe.api.provisioning.region_proxy.get_instance_region", return_value="US"),
            patch(
                "ee.partners.stripe.api.provisioning.region_proxy.requests.request",
                return_value=_fake_upstream({"status": "complete", "id": "42"}),
            ) as proxied,
        ):
            res = self._get_signed_with_bearer(f"{BASE_PATH}/provisioning/resources/42", token="pha_only_in_eu")
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert proxied.call_args.kwargs["url"].endswith(f"{BASE_PATH}/provisioning/resources/42")

    def test_unknown_auth_code_is_proxied(self):
        with (
            patch("ee.partners.stripe.api.provisioning.region_proxy.get_instance_region", return_value="US"),
            patch(
                "ee.partners.stripe.api.provisioning.region_proxy.requests.request",
                return_value=_fake_upstream({"token_type": "bearer", "access_token": "pha_eu"}),
            ) as proxied,
        ):
            res = self._post_signed(
                f"{BASE_PATH}/oauth/token",
                data={"grant_type": "authorization_code", "code": "code_only_in_eu"},
                content_type="application/x-www-form-urlencoded",
            )
        assert res.status_code == 200
        assert res.json()["access_token"] == "pha_eu"
        proxied.assert_called_once()

    def test_failed_body_region_proxy_returns_502(self):
        import requests as requests_lib

        with (
            patch("ee.partners.stripe.api.provisioning.region_proxy.get_instance_region", return_value="US"),
            patch(
                "ee.partners.stripe.api.provisioning.region_proxy.requests.request",
                side_effect=requests_lib.exceptions.ConnectionError("boom"),
            ),
        ):
            res = self._post_signed(f"{BASE_PATH}/provisioning/account_requests", data=self._account_request("EU"))
        assert res.status_code == 502
        assert res.json() == {"error": {"code": "proxy_failed", "message": "Failed to route to correct region"}}
