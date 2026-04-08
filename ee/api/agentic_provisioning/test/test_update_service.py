from unittest.mock import MagicMock, patch

from django.test import override_settings

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestProvisioningUpdateService(StripeProvisioningTestBase):
    def test_update_service_with_spt_calls_billing(self):
        token = self._get_bearer_token()
        with patch("ee.api.agentic_provisioning.views.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.return_value = None
            mock_post.return_value = mock_resp

            res = self._post_signed_with_bearer(
                f"/api/agentic/provisioning/resources/{self.team.id}/update_service",
                data={
                    "service_id": "pay_as_you_go",
                    "payment_credentials": {"stripe_payment_token": "spt_test_123"},
                },
                token=token,
            )
            assert res.status_code == 200
            assert res.json()["status"] == "complete"
            assert res.json()["service_id"] == "pay_as_you_go"
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert "stripe_payment_token" in call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))

    def test_update_service_without_spt(self):
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
