from posthog.test.base import BaseTest

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.user_permissions import UserPermissions


class WithPermissionsBase:
    user: User
    team: Team

    def permissions(self):
        return UserPermissions(user=self.user, team=self.team)


class TestUserTeamPermissions(BaseTest, WithPermissionsBase):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {
                "name": AvailableFeature.ADVANCED_PERMISSIONS,
                "key": AvailableFeature.ADVANCED_PERMISSIONS,
            }
        ]
        self.organization.save()

    def test_team_effective_membership_level(self):
        with self.assertNumQueries(2):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.MEMBER

    def test_team_effective_membership_level_updated(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        with self.assertNumQueries(2):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_effective_membership_level_does_not_belong(self):
        self.organization_membership.delete()

        permissions = UserPermissions(user=self.user)
        with self.assertNumQueries(1):
            assert permissions.team(self.team).effective_membership_level is None

    def test_team_effective_membership_level_with_explicit_membership_returns_current_level(self):
        from ee.models.rbac.access_control import AccessControl

        # Make the team private using new access control system
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        with self.assertNumQueries(2):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_ids_visible_for_user(self):
        assert self.team.id in self.permissions().team_ids_visible_for_user

    def test_team_ids_visible_for_user_no_explicit_permissions(self):
        from ee.models.rbac.access_control import AccessControl

        # Make the team private using new access control system
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        assert self.team.id not in self.permissions().team_ids_visible_for_user

    def test_team_ids_visible_for_user_explicit_permission(self):
        from ee.models.rbac.access_control import AccessControl

        # Make the team private using new access control system
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        # ExplicitTeamMembership deprecated - now using AccessControl for granular permissions
        from ee.models.rbac.access_control import AccessControl

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=self.organization_membership,
            access_level="admin",
        )

        assert self.team.id in self.permissions().team_ids_visible_for_user

    def test_team_effective_membership_level_new_access_control_non_private_team(self):
        """Test that all organization members have access to a non-private team with the new access control system"""

        # Set up team with new access control system
        # Team is not private (no AccessControl objects), so organization level is used

        # Set up user as a member
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Check effective membership level
        with self.assertNumQueries(2):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.MEMBER

    def test_team_effective_membership_level_new_access_control_private_team_admin(self):
        """Test that organization admins have access to a private team with the new access control system"""
        from ee.models.rbac.access_control import AccessControl

        # Set up team with new access control system
        # Team is not private (no AccessControl objects), so organization level is used

        # Make the team private
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        # Set up user as an admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Check effective membership level
        with self.assertNumQueries(2):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_effective_membership_level_new_access_control_private_team_member_no_access(self):
        """Test that regular members don't have access to a private team with the new access control system"""
        from ee.models.rbac.access_control import AccessControl

        # Set up team with new access control system
        # Team is not private (no AccessControl objects), so organization level is used

        # Make the team private
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        # Set up user as a member
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Check effective membership level
        with self.assertNumQueries(4):
            assert self.permissions().current_team.effective_membership_level is None

    def test_team_effective_membership_level_new_access_control_private_team_with_member_access(self):
        """Test that users with specific member access have access to a private team with the new access control system"""
        from ee.models.rbac.access_control import AccessControl

        # Set up team with new access control system
        # Team is not private (no AccessControl objects), so organization level is used

        # Make the team private
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        # Set up user as a member
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Give the member user access to the team
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=self.organization_membership,
            access_level="member",
        )

        # Check effective membership level
        with self.assertNumQueries(3):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.MEMBER

    def test_team_effective_membership_level_new_access_control_private_team_with_role_access(self):
        """Test that users with role-based access have access to a private team with the new access control system"""
        from ee.models.rbac.access_control import AccessControl
        from ee.models.rbac.role import Role, RoleMembership

        # Set up team with new access control system
        # Team is not private (no AccessControl objects), so organization level is used

        # Make the team private
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        # Set up user as a member
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Create a role
        role = Role.objects.create(name="Test Role", organization=self.organization)

        # Assign the member to the role
        RoleMembership.objects.create(
            role=role,
            user=self.user,
            organization_member=self.organization_membership,
        )

        # Give the role access to the team
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            role=role,
            access_level="member",
        )

        # Check effective membership level
        with self.assertNumQueries(4):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.MEMBER
