from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.test.base import BaseTest
from posthog.user_permissions import UserPermissions


class TestUserPermissions(BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.organization.available_features = [AvailableFeature.PROJECT_BASED_PERMISSIONING]
        self.organization.save()

    def permissions(self, **kwargs):
        options = {"user": self.user, "team": self.team, "organization": self.organization, **kwargs}

        return UserPermissions(**options)

    def test_team_effective_membership_level(self):
        with self.assertNumQueries(1):
            assert self.permissions().team_effective_membership_level == OrganizationMembership.Level.MEMBER

    def test_team_effective_membership_level_updated(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        with self.assertNumQueries(1):
            assert self.permissions().team_effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_effective_membership_level_does_not_belong(self):
        self.organization_membership.delete()

        with self.assertNumQueries(1):
            assert self.permissions().team_effective_membership_level is None

    def test_team_effective_membership_level_with_explicit_membership_returns_current_level(self):
        self.team.access_control = True
        self.team.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        with self.assertNumQueries(2):
            assert self.permissions().team_effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_effective_membership_level_with_member(self):
        self.team.access_control = True
        self.team.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        with self.assertNumQueries(2):
            assert self.permissions().team_effective_membership_level is None

    def test_team_effective_membership_level_with_explicit_membership_returns_explicit_membership(self):
        self.team.access_control = True
        self.team.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.ADMIN
        )

        with self.assertNumQueries(2):
            assert self.permissions().team_effective_membership_level == OrganizationMembership.Level.ADMIN
