from parameterized import parameterized

from posthog.accessible_teams import AccessibleTeams
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.oauth import OAuthAccessToken, OAuthRefreshToken
from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team_provisioning_config import TeamProvisioningConfig
from posthog.models.user import User
from posthog.personal_api_key_minting import mint_personal_api_key

from ee.partners.stripe.api.provisioning.core import maybe_create_provisioned_pat
from ee.partners.stripe.api.provisioning.test.base import BASE_PATH, StripeProvisioningTestBase

RESOURCES_URL = f"{BASE_PATH}/provisioning/resources"


class TestRemoveAndRotate(StripeProvisioningTestBase):
    def _mint_own_key(self, user: User, like: PersonalAPIKey) -> PersonalAPIKey:
        return mint_personal_api_key(
            user,
            label=like.label,
            scopes=like.scopes,
            teams=AccessibleTeams.for_user(user, [self.team.id]),
            organization_ids=[str(self.team.organization_id)],
        ).key

    def test_rotate_credentials_issues_new_api_key_and_replaces_every_members_pat(self):
        token = self._get_bearer_token()
        create = self._post_signed_with_bearer(RESOURCES_URL, data={"service_id": "analytics"}, token=token)
        assert create.status_code == 200
        initial_pat = PersonalAPIKey.objects.get(user=self.user, provisioned_by=self.stripe_app)
        teammate = User.objects.create_and_join(
            organization=self.organization, email="teammate@example.com", password="testpass"
        )
        assert maybe_create_provisioned_pat(teammate, self.team, self.stripe_app, "query:read")
        own_key = self._mint_own_key(self.user, initial_pat)
        original_api_key = self.team.api_token

        res = self._post_signed_with_bearer(
            f"{RESOURCES_URL}/{self.team.id}/rotate_credentials", data={"label_prefix": "Rotated"}, token=token
        )

        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "complete"
        rotated_api_key = body["complete"]["access_configuration"]["api_key"]
        assert rotated_api_key != original_api_key
        self.team.refresh_from_db()
        assert self.team.api_token == rotated_api_key
        assert body["complete"]["access_configuration"]["personal_api_key"].startswith("phx_")
        assert not PersonalAPIKey.objects.filter(id=initial_pat.id).exists()
        assert not PersonalAPIKey.objects.filter(user=teammate).exists()
        rotated_pat = PersonalAPIKey.objects.get(user=self.user, provisioned_by=self.stripe_app)
        assert rotated_pat.label.startswith("Rotated - ")
        assert PersonalAPIKey.objects.filter(id=own_key.id).exists()

    @parameterized.expand([("token_refreshed_or_deleted", None), ("team_out_of_scope", [])])
    def test_rotation_with_a_bearer_that_no_longer_covers_the_team_ends_earlier_keys_and_mints_none(
        self, _name: str, remaining_scoped_teams: list[int] | None
    ) -> None:
        access_token = OAuthAccessToken.objects.get(token=self._get_bearer_token())
        assert maybe_create_provisioned_pat(self.user, self.team, self.stripe_app, "query:read")
        tokens = OAuthAccessToken.objects.filter(pk=access_token.pk)
        if remaining_scoped_teams is None:
            tokens.delete()
        else:
            tokens.update(scoped_teams=remaining_scoped_teams)

        api_key = maybe_create_provisioned_pat(
            self.user, self.team, self.stripe_app, "query:read", access_token=access_token, replace_existing=True
        )

        assert api_key is None
        assert not PersonalAPIKey.objects.filter(provisioned_by=self.stripe_app).exists()

    def test_rotate_rejects_invalid_label_prefix_with_resource_id(self):
        token = self._get_bearer_token()
        res = self._post_signed_with_bearer(
            f"{RESOURCES_URL}/{self.team.id}/rotate_credentials", data={"label_prefix": "x" * 26}, token=token
        )
        assert res.status_code == 400
        assert res.json() == {
            "status": "error",
            "id": str(self.team.id),
            "error": {"code": "invalid_label_prefix", "message": "label_prefix must be 25 characters or fewer"},
        }

    def test_remove_names_no_actor_in_another_organization_a_partner_key_reaches(self) -> None:
        token = self._get_bearer_token()
        other_organization = Organization.objects.create(name="Other org")
        teammate = User.objects.create_and_join(
            organization=self.organization, email="teammate@example.com", password="testpass"
        )
        teammate.join(organization=other_organization)
        assert maybe_create_provisioned_pat(teammate, self.team, self.stripe_app, "query:read")
        partner_key = PersonalAPIKey.objects.get(user=teammate, provisioned_by=self.stripe_app)
        PersonalAPIKey.objects.filter(id=partner_key.id).update(
            scoped_teams=[], scoped_organizations=[str(self.organization.id), str(other_organization.id)]
        )

        res = self._post_signed_with_bearer(f"{RESOURCES_URL}/{self.team.id}/remove", token=token)

        assert res.status_code == 200
        actor_per_organization = dict(
            ActivityLog.objects.filter(scope="PersonalAPIKey", item_id=partner_key.id, activity="deleted").values_list(
                "organization_id", "user_id"
            )
        )
        assert actor_per_organization == {self.organization.id: self.user.id, other_organization.id: None}

    def test_remove_detaches_resource_and_strips_token_scope(self):
        token = self._get_bearer_token()
        create = self._post_signed_with_bearer(RESOURCES_URL, data={"service_id": "analytics"}, token=token)
        assert create.status_code == 200
        assert TeamProvisioningConfig.objects.filter(team=self.team).exists()
        access_token = OAuthAccessToken.objects.get(token=token)
        teammate = User.objects.create_and_join(
            organization=self.organization, email="teammate@example.com", password="testpass", first_name="Mate"
        )
        teammate_at = OAuthAccessToken.objects.create(
            application=access_token.application,
            user=teammate,
            token="teammate_access_token_value",
            expires=access_token.expires,
            scope=access_token.scope,
            scoped_teams=[self.team.id, 99999],
        )
        teammate_rt = OAuthRefreshToken.objects.create(
            application=access_token.application,
            user=teammate,
            token="teammate_refresh_token_value",
            access_token=teammate_at,
            scoped_teams=[self.team.id, 99999],
        )

        provisioned_pat = PersonalAPIKey.objects.get(user=self.user, provisioned_by=self.stripe_app)
        own_key = self._mint_own_key(self.user, provisioned_pat)
        unrestricted_api_key = maybe_create_provisioned_pat(self.user, self.team, self.stripe_app, "query:read")
        assert unrestricted_api_key
        unrestricted_pat = PersonalAPIKey.objects.filter(provisioned_by=self.stripe_app).latest("created_at")
        PersonalAPIKey.objects.filter(id=unrestricted_pat.id).update(scoped_teams=[], scoped_organizations=[])
        assert maybe_create_provisioned_pat(self.user, self.team, self.stripe_app, "query:read")
        team_in_other_organization_pat = PersonalAPIKey.objects.filter(provisioned_by=self.stripe_app).latest(
            "created_at"
        )
        PersonalAPIKey.objects.filter(id=team_in_other_organization_pat.id).update(
            scoped_organizations=[str(Organization.objects.create(name="Other org").id)]
        )

        res = self._post_signed_with_bearer(f"{RESOURCES_URL}/{self.team.id}/remove", token=token)
        assert res.status_code == 200
        assert res.json() == {"status": "removed", "id": str(self.team.id)}
        assert not TeamProvisioningConfig.objects.filter(team=self.team).exists()
        assert not PersonalAPIKey.objects.filter(id__in=[provisioned_pat.id, unrestricted_pat.id]).exists()
        assert PersonalAPIKey.objects.filter(id__in=[own_key.id, team_in_other_organization_pat.id]).count() == 2

        # The team left the token's scope; since it was the only scoped team the
        # token itself is gone, so further calls are unauthorized.
        detail = self._get_signed_with_bearer(f"{RESOURCES_URL}/{self.team.id}", token=token)
        assert detail.status_code == 401
        teammate_at.refresh_from_db()
        teammate_rt.refresh_from_db()
        assert teammate_at.scoped_teams == [99999]
        assert teammate_rt.scoped_teams == [99999]
