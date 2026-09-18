"""
Tests for User.teams property with the new AccessControl system.
This ensures that team access filtering works correctly with the RBAC system.
"""

from posthog.test.base import BaseTest

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership


class TestUserTeamsAccessControl(BaseTest):
    """Test the User.teams property with the new AccessControl system."""

    def setUp(self):
        super().setUp()
        # Enable access control and role-based access for the organization
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

    def test_user_teams_without_access_control(self):
        """Test that without access control, user sees all teams in their organization."""
        # Disable access control
        self.organization.available_product_features = []
        self.organization.save()

        # Create additional teams
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        team3 = Team.objects.create(organization=self.organization, name="Team 3")

        # User should see all teams
        user_teams = self.user.teams.all()
        self.assertEqual(user_teams.count(), 3)
        self.assertIn(self.team, user_teams)
        self.assertIn(team2, user_teams)
        self.assertIn(team3, user_teams)

    def test_user_teams_with_no_private_teams(self):
        """Test that with advanced permissions but no private teams, user sees all teams."""
        # Create additional teams
        team2 = Team.objects.create(organization=self.organization, name="Team 2")
        team3 = Team.objects.create(organization=self.organization, name="Team 3")

        # User should see all teams (no access controls set)
        user_teams = self.user.teams.all()
        self.assertEqual(user_teams.count(), 3)
        self.assertIn(self.team, user_teams)
        self.assertIn(team2, user_teams)
        self.assertIn(team3, user_teams)

    def test_user_teams_with_private_team_no_access(self):
        """Test that users cannot see private teams they don't have access to."""
        # Create a private team
        private_team = Team.objects.create(organization=self.organization, name="Private Team")
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="none",
            organization_member=None,
            role=None,
        )

        # User should only see the original team, not the private one
        user_teams = self.user.teams.all()
        self.assertEqual(user_teams.count(), 1)
        self.assertIn(self.team, user_teams)
        self.assertNotIn(private_team, user_teams)

    def test_user_teams_with_private_team_explicit_access(self):
        """Test that users can see private teams they have explicit access to."""
        # Create a private team
        private_team = Team.objects.create(organization=self.organization, name="Private Team")
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="none",
            organization_member=None,
            role=None,
        )

        # Give user explicit access
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="member",
            organization_member=self.organization_membership,
            role=None,
        )

        # User should see both teams
        user_teams = self.user.teams.all()
        self.assertEqual(user_teams.count(), 2)
        self.assertIn(self.team, user_teams)
        self.assertIn(private_team, user_teams)

    def test_user_teams_with_private_team_role_based_access(self):
        """Test that users can see private teams they have role-based access to."""
        # Create a private team
        private_team = Team.objects.create(organization=self.organization, name="Private Team")
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="none",
            organization_member=None,
            role=None,
        )

        # Create a role and assign user to it
        role = Role.objects.create(name="Developer", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=self.user,
            organization_member=self.organization_membership,
        )

        # Give role access to the private team
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="admin",
            organization_member=None,
            role=role,
        )

        # User should see both teams
        user_teams = self.user.teams.all()
        self.assertEqual(user_teams.count(), 2)
        self.assertIn(self.team, user_teams)
        self.assertIn(private_team, user_teams)

    def test_user_teams_ignores_role_membership_from_another_organization(self):
        other_organization = Organization.objects.create(name="Other organization")
        other_team = Team.objects.create(organization=other_organization, name="Other private team")
        OrganizationMembership.objects.create(
            organization=other_organization,
            user=self.user,
            level=OrganizationMembership.Level.MEMBER,
        )
        role = Role.objects.create(name="Other organization role", organization=other_organization)
        RoleMembership.objects.create(
            role=role,
            user=self.user,
            organization_member=self.organization_membership,
        )
        AccessControl.objects.create(
            team=other_team,
            resource="project",
            resource_id=str(other_team.id),
            access_level="none",
            organization_member=None,
            role=None,
        )
        AccessControl.objects.create(
            team=other_team,
            resource="project",
            resource_id=str(other_team.id),
            access_level="member",
            organization_member=None,
            role=role,
        )

        assert other_team not in self.user.teams.all()

    def test_user_teams_role_based_access_inert_without_role_based_access_feature(self):
        """Role-backed project AccessControl rows must NOT grant team visibility when the
        org lacks ROLE_BASED_ACCESS — mirrors the UI gate."""
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()

        private_team = Team.objects.create(organization=self.organization, name="Private Team")
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="none",
            organization_member=None,
            role=None,
        )

        role = Role.objects.create(name="Developer", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=self.user,
            organization_member=self.organization_membership,
        )
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="admin",
            organization_member=None,
            role=role,
        )

        self.user.__dict__.pop("teams", None)  # bust cached_property if it was set
        user_teams = self.user.teams.all()
        self.assertEqual(user_teams.count(), 1)
        self.assertIn(self.team, user_teams)
        self.assertNotIn(private_team, user_teams)

    def test_organization_admin_sees_all_teams(self):
        """Test that organization admins can see all teams, including private ones."""
        # Make user an admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create a private team without giving user explicit access
        private_team = Team.objects.create(organization=self.organization, name="Private Team")
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="none",
            organization_member=None,
            role=None,
        )

        # Clear the cached property to get fresh data
        del self.user.teams

        # Admin should see all teams
        user_teams = self.user.teams.all()
        self.assertEqual(user_teams.count(), 2)
        self.assertIn(self.team, user_teams)
        self.assertIn(private_team, user_teams)

    def test_organization_owner_sees_all_teams(self):
        """Test that organization owners can see all teams, including private ones."""
        # Make user an owner
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

        # Create a private team without giving user explicit access
        private_team = Team.objects.create(organization=self.organization, name="Private Team")
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="none",
            organization_member=None,
            role=None,
        )

        # Clear the cached property to get fresh data
        del self.user.teams

        # Owner should see all teams
        user_teams = self.user.teams.all()
        self.assertEqual(user_teams.count(), 2)
        self.assertIn(self.team, user_teams)
        self.assertIn(private_team, user_teams)

    def test_user_teams_ignores_explicit_access_granted_to_another_member(self):
        """Test that a grant on someone else's membership stays with that member."""
        private_team = Team.objects.create(organization=self.organization, name="Private Team")
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="none",
            organization_member=None,
            role=None,
        )

        other_user = self._create_user("other@posthog.com")
        other_membership = OrganizationMembership.objects.get(organization=self.organization, user=other_user)
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="member",
            organization_member=other_membership,
            role=None,
        )

        self.assertNotIn(private_team, self.user.teams.all())
        self.assertIn(private_team, other_user.teams.all())

    def test_organization_admin_does_not_see_private_teams_in_another_organization(self):
        """Test that admin level in one organization grants no access in another."""
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        other_organization = Organization.objects.create(name="Other Organization")
        # Both organizations carry the feature, because the gate reads whichever
        # membership comes back first.
        other_organization.available_product_features = self.organization.available_product_features
        other_organization.save()
        OrganizationMembership.objects.create(
            organization=other_organization,
            user=self.user,
            level=OrganizationMembership.Level.MEMBER,
        )

        own_private_team = Team.objects.create(organization=self.organization, name="Own Private Team")
        other_private_team = Team.objects.create(organization=other_organization, name="Other Private Team")
        for team in [own_private_team, other_private_team]:
            AccessControl.objects.create(
                team=team,
                resource="project",
                resource_id=str(team.id),
                access_level="none",
                organization_member=None,
                role=None,
            )

        del self.user.teams  # Clear cached property

        user_teams = self.user.teams.all()
        self.assertIn(own_private_team, user_teams)
        self.assertNotIn(other_private_team, user_teams)

    def test_user_teams_multiple_organizations(self):
        """Test that user only sees teams from organizations they belong to."""
        # Create another organization with teams
        other_org = Organization.objects.create(name="Other Organization")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        # User should only see teams from their organization
        user_teams = self.user.teams.all()
        self.assertEqual(user_teams.count(), 1)
        self.assertIn(self.team, user_teams)
        self.assertNotIn(other_team, user_teams)

    def test_user_teams_complex_scenario(self):
        """Test a complex scenario with multiple teams, roles, and access controls."""
        # Create multiple teams
        public_team = Team.objects.create(organization=self.organization, name="Public Team")
        private_team_1 = Team.objects.create(organization=self.organization, name="Private Team 1")
        private_team_2 = Team.objects.create(organization=self.organization, name="Private Team 2")
        private_team_3 = Team.objects.create(organization=self.organization, name="Private Team 3")

        # Make teams private
        for team in [private_team_1, private_team_2, private_team_3]:
            AccessControl.objects.create(
                team=team,
                resource="project",
                resource_id=str(team.id),
                access_level="none",
                organization_member=None,
                role=None,
            )

        # Give user explicit access to private_team_1
        AccessControl.objects.create(
            team=private_team_1,
            resource="project",
            resource_id=str(private_team_1.id),
            access_level="member",
            organization_member=self.organization_membership,
            role=None,
        )

        # Create role and give role access to private_team_2
        role = Role.objects.create(name="QA", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=self.user,
            organization_member=self.organization_membership,
        )
        AccessControl.objects.create(
            team=private_team_2,
            resource="project",
            resource_id=str(private_team_2.id),
            access_level="admin",
            organization_member=None,
            role=role,
        )

        # private_team_3 should not be accessible (no explicit access or role access)

        # User should see: original team, public team, private_team_1, private_team_2
        # User should NOT see: private_team_3
        user_teams = self.user.teams.all()
        self.assertEqual(user_teams.count(), 4)
        self.assertIn(self.team, user_teams)
        self.assertIn(public_team, user_teams)
        self.assertIn(private_team_1, user_teams)
        self.assertIn(private_team_2, user_teams)
        self.assertNotIn(private_team_3, user_teams)

    def test_user_teams_with_both_explicit_and_role_access(self):
        """Test that user sees team when they have both explicit and role access."""
        # Create a private team
        private_team = Team.objects.create(organization=self.organization, name="Private Team")
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="none",
            organization_member=None,
            role=None,
        )

        # Give user explicit access
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="member",
            organization_member=self.organization_membership,
            role=None,
        )

        # Also give role-based access
        role = Role.objects.create(name="Developer", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=self.user,
            organization_member=self.organization_membership,
        )
        AccessControl.objects.create(
            team=private_team,
            resource="project",
            resource_id=str(private_team.id),
            access_level="admin",
            organization_member=None,
            role=role,
        )

        # User should see the team (no duplication)
        user_teams = self.user.teams.all()
        self.assertEqual(user_teams.count(), 2)
        self.assertIn(self.team, user_teams)
        self.assertIn(private_team, user_teams)

    def test_user_teams_ordering(self):
        """Test that teams are ordered correctly."""
        # Create additional teams
        Team.objects.create(organization=self.organization, name="Team A")
        Team.objects.create(organization=self.organization, name="Team B")

        # Get teams and check they're ordered by ID
        user_teams = list(self.user.teams.all())
        team_ids = [team.id for team in user_teams]
        self.assertEqual(team_ids, sorted(team_ids))

    def test_user_teams_caching(self):
        """Test that the teams property is cached correctly."""
        # The property is cached, so repeated access returns the same queryset.
        teams_1 = self.user.teams
        self.assertIs(self.user.teams, teams_1)

        new_team = Team.objects.create(organization=self.organization, name="New Team")

        # The cached value is a queryset, not a snapshot of ids, so it stays current.
        self.assertIn(new_team, self.user.teams.all())

        del self.user.teams  # Clear cached property
        self.assertIn(new_team, self.user.teams.all())

    def test_user_teams_resolves_in_a_single_team_read(self):
        for name in ["Team A", "Team B", "Team C"]:
            Team.objects.create(organization=self.organization, name=name)

        # One read for the organization's product features, one for the teams themselves.
        with self.assertNumQueries(2):
            teams = list(self.user.teams)
        self.assertEqual(len(teams), 4)
