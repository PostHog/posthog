from unittest.mock import patch

from django.test import override_settings

from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, StripeProvisioningTestBase


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestProvisioningRotateCredentials(StripeProvisioningTestBase):
    def test_rotate_returns_new_access_configuration(self):
        token = self._get_bearer_token()
        original_api_token = self.team.api_token
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["id"] == str(self.team.id)
        rotated_key = data["complete"]["access_configuration"]["api_key"]
        assert rotated_key != original_api_token
        self.team.refresh_from_db()
        assert rotated_key == self.team.api_token
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
            data={"service_id": "analytics"},
            token=token,
        )
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        assert res.json()["service_id"] == "analytics"

    def test_rotate_defaults_service_id_to_posthog(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        assert res.status_code == 200
        assert res.json()["service_id"] == "analytics"

    def test_rotate_includes_new_personal_api_key(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        assert res.status_code == 200
        personal_api_key = res.json()["complete"]["access_configuration"]["personal_api_key"]
        assert personal_api_key.startswith("phx_")

    def test_rotate_preserves_existing_pats(self):
        token = self._get_bearer_token()
        self._post_signed_with_bearer(
            "/api/agentic/provisioning/resources",
            data={"service_id": "analytics"},
            token=token,
        )
        initial_pat = PersonalAPIKey.objects.filter(user=self.user, label__startswith="Stripe Projects").first()
        assert initial_pat is not None

        self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        assert PersonalAPIKey.objects.filter(id=initial_pat.id).exists()
        assert PersonalAPIKey.objects.filter(user=self.user, label__startswith="Stripe Projects").count() == 2

    @patch("posthog.models.team.team.Team.reset_token_and_save", side_effect=Exception("db error"))
    def test_rotate_returns_500_when_reset_token_fails(self, _mock_reset):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        assert res.status_code == 500
        assert res.json()["error"]["code"] == "credential_rotation_failed"
