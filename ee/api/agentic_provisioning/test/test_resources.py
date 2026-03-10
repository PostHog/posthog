from django.test import override_settings

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestProvisioningResources(StripeProvisioningTestBase):
    def test_create_resource_returns_complete(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "product_analytics"},
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["id"] == str(self.team.id)
        assert "api_key" in data["complete"]["access_configuration"]
        assert "host" in data["complete"]["access_configuration"]

    def test_get_resource_returns_complete(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}",
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["id"] == str(self.team.id)

    def test_get_resource_wrong_team_returns_403(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(
            "/api/agentic/provisioning/resources/99999",
            token=token,
        )
        assert res.status_code == 403

    def test_get_resource_invalid_id_returns_400(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(
            "/api/agentic/provisioning/resources/not-a-number",
            token=token,
        )
        assert res.status_code == 400

    def test_create_resource_missing_bearer_returns_401(self):
        res = self._post_signed("/api/agentic/provisioning/resources", data={"service_id": "product_analytics"})
        assert res.status_code == 401

    def test_create_resource_invalid_bearer_returns_401(self):
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "product_analytics"},
            token="pha_invalid_token",
        )
        assert res.status_code == 401

    def test_get_resource_missing_bearer_returns_401(self):
        res = self._get_signed(f"/api/agentic/provisioning/resources/{self.team.id}")
        assert res.status_code == 401

    def test_get_resource_returns_service_id_from_create(self):
        token = self._get_bearer_token()
        self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "session_replay"},
            token=token,
        )
        res = self._get_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}",
            token=token,
        )
        assert res.json()["service_id"] == "session_replay"

    def test_get_resource_defaults_service_id_without_create(self):
        token = self._get_bearer_token()
        res = self._get_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}",
            token=token,
        )
        assert res.json()["service_id"] == "posthog"

    def test_create_resource_defaults_service_id_to_posthog(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={},
            token=token,
        )
        assert res.status_code == 200
        assert res.json()["service_id"] == "posthog"
