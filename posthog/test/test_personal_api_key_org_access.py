from posthog.test.base import BaseTest

from posthog.models import Organization, Team, User
from posthog.models.personal_api_key import PersonalAPIKey, get_organization_personal_api_keys
from posthog.models.utils import generate_random_token_personal, hash_key_value


class TestGetOrganizationPersonalAPIKeys(BaseTest):
    def _create_key(self, user, scoped_organizations=None, scoped_teams=None, label="key"):
        return PersonalAPIKey.objects.create(
            user=user,
            label=label,
            secure_value=hash_key_value(generate_random_token_personal()),
            scopes=["insight:read"],
            scoped_organizations=scoped_organizations,
            scoped_teams=scoped_teams,
        )

    def test_includes_unscoped_org_scoped_and_team_scoped_member_keys(self):
        member = User.objects.create_and_join(self.organization, "member@x.com", None)
        unscoped = self._create_key(member, label="unscoped")
        org_scoped = self._create_key(member, scoped_organizations=[str(self.organization.id)], label="org")
        team_scoped = self._create_key(member, scoped_teams=[self.team.id], label="team")

        result_ids = set(get_organization_personal_api_keys(self.organization).values_list("id", flat=True))

        assert result_ids == {unscoped.id, org_scoped.id, team_scoped.id}

    def test_excludes_keys_scoped_to_other_org_and_other_teams(self):
        member = User.objects.create_and_join(self.organization, "member2@x.com", None)
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other team")
        self._create_key(member, scoped_organizations=[str(other_org.id)], label="other-org")
        self._create_key(member, scoped_teams=[other_team.id], label="other-team")

        assert get_organization_personal_api_keys(self.organization).count() == 0

    def test_excludes_keys_of_non_members(self):
        outsider = User.objects.create(email="outsider@x.com")
        self._create_key(outsider, label="outsider-unscoped")

        assert get_organization_personal_api_keys(self.organization).count() == 0

    def test_deduplicates(self):
        member = User.objects.create_and_join(self.organization, "member3@x.com", None)
        self._create_key(
            member,
            scoped_organizations=[str(self.organization.id)],
            scoped_teams=[self.team.id],
            label="both",
        )

        assert get_organization_personal_api_keys(self.organization).count() == 1
