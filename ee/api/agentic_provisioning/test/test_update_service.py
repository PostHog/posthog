from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestProvisioningUpdateService(StripeProvisioningTestBase):
    @patch("ee.api.agentic_provisioning.views.requests.post")
    @patch("ee.billing.billing_manager.build_billing_token", return_value="test_billing_token")
    @patch("posthog.cloud_utils.get_cached_instance_license")
    def test_update_service_with_spt_calls_billing(self, mock_license, mock_build_token, mock_post):
        mock_license.return_value = MagicMock()
        mock_post.return_value = MagicMock(status_code=200)

        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={
                "service_id": "pay_as_you_go",
                "payment_credentials": {
                    "type": "stripe_payment_token",
                    "stripe_payment_token": "spt_test_123",
                },
            },
            token=token,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "complete"
        assert res.json()["service_id"] == "pay_as_you_go"

        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        assert "/api/activate/authorize" in call_args[0]
        assert call_kwargs["json"] == {"shared_payment_token": "spt_test_123"}

    @parameterized.expand(
        [
            ("billing_inactive", False, 400, "billing_activation_failed"),
            ("billing_already_active", True, 200, "complete"),
        ]
    )
    @patch("ee.api.agentic_provisioning.views.requests.get")
    @patch("ee.api.agentic_provisioning.views.requests.post")
    @patch("ee.billing.billing_manager.build_billing_token", return_value="test_billing_token")
    @patch("posthog.cloud_utils.get_cached_instance_license")
    def test_update_service_spt_failure(
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
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={
                "service_id": "pay_as_you_go",
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
            assert body["service_id"] == "pay_as_you_go"

    def test_update_service_without_spt_to_free_succeeds(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={"service_id": "free"},
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["service_id"] == "free"
        assert "api_key" in data["complete"]["access_configuration"]
        assert "host" in data["complete"]["access_configuration"]

    def test_update_service_to_pay_as_you_go_without_spt_returns_error(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={"service_id": "pay_as_you_go"},
            token=token,
        )
        assert res.status_code == 400
        body = res.json()
        assert body["status"] == "error"
        assert body["error"]["code"] == "requires_payment_credentials"

    def test_update_service_rejects_unknown_service_id(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={"service_id": "unknown_service"},
            token=token,
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "unknown_service"

    def test_update_service_requires_service_id(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={},
            token=token,
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "missing_service_id"

    def test_update_service_wrong_team_returns_403(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources/99999/update_service",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 403

    def test_update_service_missing_bearer_returns_401(self):
        res = self._post_signed(
            f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
            data={"service_id": "analytics"},
        )
        assert res.status_code == 401

    def test_update_service_invalid_resource_id(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources/not-a-number/update_service",
            data={"service_id": "analytics"},
            token=token,
        )
        assert res.status_code == 400
