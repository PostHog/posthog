from django.test import override_settings

from posthog.models.oauth import OAuthAccessToken
from posthog.models.team.team import Team

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_APP_SECRET_KEY=HMAC_SECRET)
class TestProvisioningRotateCredentials(StripeProvisioningTestBase):
    def test_rotate_returns_access_configuration(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["id"] == str(self.team.id)
        assert data["complete"]["access_configuration"]["api_key"] == self.team.api_token
        assert "host" in data["complete"]["access_configuration"]

    def test_rotate_wrong_team_returns_403(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources/99999/rotate_credentials",
            token=token,
        )
        assert res.status_code == 403

    def test_rotate_invalid_id_returns_400(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources/not-a-number/rotate_credentials",
            token=token,
        )
        assert res.status_code == 400

    def test_rotate_missing_bearer_returns_401(self):
        res = self._post_signed(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
        )
        assert res.status_code == 401

    def test_rotate_deleted_team_returns_404(self):
        token = self._get_bearer_token()
        team_id = self.team.id
        access_token = OAuthAccessToken.objects.get(token=token)
        access_token.scoped_teams = [team_id]
        access_token.save(update_fields=["scoped_teams"])
        Team.objects.filter(id=team_id).delete()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{team_id}/rotate_credentials",
            token=token,
        )
        assert res.status_code == 404

    def test_rotate_returns_service_id_from_create(self):
        token = self._get_bearer_token()
        self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "session_replay"},
            token=token,
        )
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        assert res.json()["service_id"] == "session_replay"
