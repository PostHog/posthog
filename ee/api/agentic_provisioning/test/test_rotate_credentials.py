from unittest.mock import patch

from parameterized import parameterized

from posthog.accessible_teams import AccessibleTeams
from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.personal_api_key_minting import mint_personal_api_key

from ee.api.agentic_provisioning.credentials import maybe_create_provisioned_pat
from ee.api.agentic_provisioning.test.base import ProvisioningTestBase


class TestProvisioningRotateCredentials(ProvisioningTestBase):
    def test_rotate_returns_new_access_configuration(self):
        token = self._get_bearer_token()
        original_api_token = self.team.api_token
        res = self._post_with_bearer(
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
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources/99999/rotate_credentials",
            token=token,
        )
        assert res.status_code == 403

    def test_rotate_invalid_id_returns_400(self):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            "/api/agentic/provisioning/resources/not-a-number/rotate_credentials",
            token=token,
        )
        assert res.status_code == 400

    def test_rotate_missing_bearer_returns_401(self):
        res = self._post_api(
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
        res = self._post_with_bearer(
            f"/api/agentic/provisioning/resources/{team_id}/rotate_credentials",
            token=token,
        )
        assert res.status_code == 404

    def test_rotate_includes_new_personal_api_key(self):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        assert res.status_code == 200
        personal_api_key = res.json()["complete"]["access_configuration"]["personal_api_key"]
        assert personal_api_key.startswith("phx_")

    def test_rotate_omits_pat_when_app_gate_off(self):
        token = self._get_bearer_token()
        app = self.partner
        app.update_provisioning(issues_personal_api_key=False)
        res = self._post_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        assert res.status_code == 200
        assert "personal_api_key" not in res.json()["complete"]["access_configuration"]

    def test_rotate_pat_is_scoped_to_authorized_team(self):
        token = self._get_bearer_token()
        self._post_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        pat = PersonalAPIKey.objects.filter(user=self.user, label=self.team.name[:40]).order_by("-created_at").first()
        assert pat is not None
        assert pat.scoped_teams == [self.team.id]
        assert pat.scoped_organizations == [str(self.team.organization_id)]

    def test_rotate_replaces_the_partners_pats_for_every_member_and_keeps_the_users_own_key(self):
        token = self._get_bearer_token()
        self._post_with_bearer(
            "/api/agentic/provisioning/resources",
            token=token,
        )
        initial_pat = PersonalAPIKey.objects.get(user=self.user, provisioned_by=self.partner)
        teammate = User.objects.create_and_join(
            organization=self.organization, email="teammate@example.com", password="testpass"
        )
        assert maybe_create_provisioned_pat(teammate, self.team, self.partner, "query:read")
        own_key = mint_personal_api_key(
            self.user,
            label=initial_pat.label,
            scopes=initial_pat.scopes,
            teams=AccessibleTeams.for_user(self.user, [self.team.id]),
            organization_ids=[str(self.team.organization_id)],
        ).key

        res = self._post_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )

        assert res.status_code == 200
        assert not PersonalAPIKey.objects.filter(id=initial_pat.id).exists()
        assert not PersonalAPIKey.objects.filter(user=teammate).exists()
        rotated_pat = PersonalAPIKey.objects.get(user=self.user, provisioned_by=self.partner)
        assert rotated_pat.scoped_teams == [self.team.id]
        assert PersonalAPIKey.objects.filter(id=own_key.id).exists()

    @patch("posthog.models.team.team.Team.reset_token_and_save", side_effect=Exception("db error"))
    def test_rotate_returns_500_when_reset_token_fails(self, _mock_reset):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            token=token,
        )
        assert res.status_code == 500
        assert res.json()["error"]["code"] == "credential_rotation_failed"

    def test_rotate_with_label_prefix_uses_prefix_for_pat(self):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
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
    @patch("ee.api.agentic_provisioning.serializers.capture_provisioning_event")
    def test_rotate_invalid_label_prefix_returns_400_and_captures_event(self, _name, label_prefix, mock_capture_event):
        token = self._get_bearer_token()
        res = self._post_with_bearer(
            f"/api/agentic/provisioning/resources/{self.team.id}/rotate_credentials",
            data={"label_prefix": label_prefix},
            token=token,
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "invalid_label_prefix"
        mock_capture_event.assert_any_call("credential_rotation", "error", error_code="invalid_label_prefix")
