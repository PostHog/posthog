from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team

from ee.api.agentic_provisioning.test.base import HMAC_SECRET, ProvisioningTestBase


@override_settings(STRIPE_SIGNING_SECRET=HMAC_SECRET)
class TestProvisioningRotateCredentials(ProvisioningTestBase):
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

    def test_rotate_pat_is_scoped_to_authorized_team(self):
        token = self._get_bearer_token()
        self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        pat = (
            PersonalAPIKey.objects.filter(user=self.user, label__startswith="Stripe Projects")
            .order_by("-created_at")
            .first()
        )
        assert pat is not None
        assert pat.scoped_teams == [self.team.id]
        assert pat.scoped_organizations == [str(self.team.organization_id)]

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

    def test_rotate_with_label_prefix_uses_prefix_for_pat(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            data={"label_prefix": "Acme Co"},
            token=token,
        )
        assert res.status_code == 200
        pat = PersonalAPIKey.objects.filter(user=self.user).order_by("-created_at").first()
        assert pat is not None
        assert pat.label.startswith("Acme Co - ")

    @parameterized.expand(
        [
            ("too_long", "a" * 26),
            ("control_char_newline", "Bad\nLabel"),
            ("bidi_override", "Bad‮Label"),
            ("non_string", 123),
        ]
    )
    @patch("ee.api.agentic_provisioning.views._capture_provisioning_event")
    def test_rotate_invalid_label_prefix_returns_400_and_captures_event(self, _name, label_prefix, mock_capture_event):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            data={"label_prefix": label_prefix},
            token=token,
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_label_prefix"
        mock_capture_event.assert_any_call("credential_rotation", "error", error_code="invalid_label_prefix")
