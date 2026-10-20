import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.accessible_teams import AccessibleTeams, CredentialScopeDenied
from posthog.models import Organization, PersonalAPIKey, User
from posthog.personal_api_key_minting import mint_personal_api_key


class TestMintPersonalAPIKey(BaseTest):
    @parameterized.expand(
        [
            ("teams_checked_for_another_user", "other_user_teams", "own_organization"),
            ("organization_owner_is_not_in", "own_teams", "other_organization"),
        ]
    )
    def test_refuses_scope_not_checked_for_the_owner(self, _name: str, teams: str, organization: str) -> None:
        other_user = User.objects.create_and_join(self.organization, "other@example.com", None)
        other_organization = Organization.objects.create(name="Other Organization")
        teams_by_name = {
            "own_teams": AccessibleTeams.for_user(self.user, [self.team.id]),
            "other_user_teams": AccessibleTeams.for_user(other_user, [self.team.id]),
        }
        organization_ids_by_name = {
            "own_organization": [str(self.organization.id)],
            "other_organization": [str(other_organization.id)],
        }

        with pytest.raises(CredentialScopeDenied):
            mint_personal_api_key(
                self.user,
                label="key",
                scopes=["*"],
                teams=teams_by_name[teams],
                organization_ids=organization_ids_by_name[organization],
            )

        self.assertFalse(PersonalAPIKey.objects.filter(user=self.user).exists())
