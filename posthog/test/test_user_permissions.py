from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.user_permissions import UserPermissions

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight

from ee.models.dashboard_privilege import DashboardPrivilege


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
                "name": AvailableFeature.ACCESS_CONTROL,
                "key": AvailableFeature.ACCESS_CONTROL,
            },
            {
                "name": AvailableFeature.ROLE_BASED_ACCESS,
                "key": AvailableFeature.ROLE_BASED_ACCESS,
            },
        ]
        self.organization.save()

    def test_team_effective_membership_level(self):
        # When no AccessControl rows exist, the default project access level is "admin"
        # so all org members get ADMIN effective membership level
        with self.assertNumQueries(3):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

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
        from products.access_control.backend.models.access_control import AccessControl

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
        from products.access_control.backend.models.access_control import AccessControl

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
        from products.access_control.backend.models.access_control import AccessControl

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
        from products.access_control.backend.models.access_control import AccessControl

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=self.organization_membership,
            access_level="admin",
        )

        assert self.team.id in self.permissions().team_ids_visible_for_user

    def test_team_effective_membership_level_new_access_control_non_private_team(self):
        """Test that all organization members have access to a non-private team with the new access control system.
        When no AccessControl rows exist, the default project access level is "admin",
        so all org members get ADMIN effective membership level."""

        # Set up team with new access control system
        # Team is not private (no AccessControl objects), default access level is admin

        # Set up user as a member
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Check effective membership level - defaults to ADMIN when no access controls exist
        with self.assertNumQueries(3):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_effective_membership_level_new_access_control_private_team_admin(self):
        """Test that organization admins have access to a private team with the new access control system"""
        from products.access_control.backend.models.access_control import AccessControl

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
        from products.access_control.backend.models.access_control import AccessControl

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
        with self.assertNumQueries(3):
            assert self.permissions().current_team.effective_membership_level is None

    def test_team_effective_membership_level_new_access_control_private_team_with_member_access(self):
        """Test that users with specific member access have access to a private team with the new access control system"""
        from products.access_control.backend.models.access_control import AccessControl

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
        from products.access_control.backend.models.access_control import AccessControl
        from products.access_control.backend.models.role import Role, RoleMembership

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
        with self.assertNumQueries(3):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.MEMBER

    def test_team_effective_membership_level_higher_project_membership_than_org_membership(self):
        """Test that users with admin project access will have its effective membership level at admin"""
        from products.access_control.backend.models.access_control import AccessControl

        # Set up user as a member
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Give the member admin access to the team
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=self.organization_membership,
            access_level="admin",
        )

        assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_effective_membership_level_with_higher_role_based_access(self):
        """Test that users with admin role-based access have its effective membership level at admin"""
        from products.access_control.backend.models.access_control import AccessControl
        from products.access_control.backend.models.role import Role, RoleMembership

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
            access_level="admin",
        )

        # Check effective membership level
        with self.assertNumQueries(3):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_effective_membership_level_role_based_access_inert_without_role_based_access_feature(self):
        """Role-backed project AccessControl rows must NOT take effect when the org lacks
        ROLE_BASED_ACCESS — mirrors the UI gate on the project access settings page."""
        from products.access_control.backend.models.access_control import AccessControl
        from products.access_control.backend.models.role import Role, RoleMembership

        # Drop ROLE_BASED_ACCESS, keep ACCESS_CONTROL
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        role = Role.objects.create(name="Test Role", organization=self.organization)
        RoleMembership.objects.create(role=role, user=self.user, organization_member=self.organization_membership)

        # Make the team private and grant the role admin via project-level role override
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            role=role,
            access_level="admin",
        )

        # Without ROLE_BASED_ACCESS the role override is inert, so the private-team default ("none") applies
        assert self.permissions().current_team.effective_membership_level is None

    def test_team_effective_membership_level_lower_project_membership_than_org_membership(self):
        """Test that users with admin org access maintain their admin level even with lower member project access"""
        from products.access_control.backend.models.access_control import AccessControl

        # Set up user as admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Give the user member access to the team
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=self.organization_membership,
            access_level="member",
        )

        assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_effective_membership_level_default_access_level_admin(self):
        """Test that org members get admin level when the project default access level is set to admin"""
        from products.access_control.backend.models.access_control import AccessControl

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Set the project's default access level to admin (no specific member or role)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="admin",
        )

        assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_effective_membership_level_default_access_level_member(self):
        """Test that org members get member level when the project default access level is set to member"""
        from products.access_control.backend.models.access_control import AccessControl

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Set the project's default access level to member
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="member",
        )

        assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.MEMBER

    def test_team_effective_membership_level_direct_access_overrides_default(self):
        """Test that direct user access overrides the project default access level"""
        from products.access_control.backend.models.access_control import AccessControl

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Set the project's default access level to member
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="member",
        )

        # Give the user direct admin access, which should override the default
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=self.organization_membership,
            access_level="admin",
        )

        assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_role_admin_access_overrides_direct_member_access(self):
        """
        BUG TEST: When a user has both:
        1. Direct MEMBER access to a project
        2. Role-based ADMIN access to the same project

        The role admin access should take precedence and return ADMIN level.
        Currently this fails because direct member access returns early without checking roles.
        """
        from products.access_control.backend.models.access_control import AccessControl
        from products.access_control.backend.models.role import Role, RoleMembership

        # Set up user as organization member (not admin)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Step 1: Give user direct MEMBER access to the project
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=self.organization_membership,
            access_level="member",
        )

        # Step 2: Create a role with ADMIN access to the same project
        admin_role = Role.objects.create(name="Project Admin Role", organization=self.organization)

        # Step 3: Assign the user to this admin role
        RoleMembership.objects.create(
            role=admin_role,
            user=self.user,
            organization_member=self.organization_membership,
        )

        # Step 4: Give the role ADMIN access to the project
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            role=admin_role,
            access_level="admin",
        )

        # Expected: Should return ADMIN level (role access trumps direct access)
        # Currently fails: Returns MEMBER level (direct access returned early)
        assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def _grant_project_access(self, access_level: str, *, member=None, role=None) -> None:
        from products.access_control.backend.models.access_control import AccessControl

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=member,
            role=role,
            access_level=access_level,
        )

    def _grant_project_access_via_new_role(self, access_level: str, *, legacy_membership: bool = False) -> None:
        from products.access_control.backend.models.role import Role, RoleMembership

        role = Role.objects.create(name=f"Role {access_level}", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=self.user,
            organization_member=None if legacy_membership else self.organization_membership,
        )
        self._grant_project_access(access_level, role=role)

    @parameterized.expand(
        [
            ("denial", "none", "member", OrganizationMembership.Level.MEMBER),
            ("grant", "admin", "none", None),
        ]
    )
    def test_role_rule_from_another_organization_is_ignored(self, _name, role_level, default_level, expected_level):
        # Nothing scopes the role on an AccessControl row to the project's organization, so a rule
        # can name a role the user holds in an unrelated organization
        from products.access_control.backend.models.access_control import AccessControl
        from products.access_control.backend.models.role import Role, RoleMembership

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self._grant_project_access(default_level)

        other_organization = Organization.objects.create(name="Other organization")
        other_membership = OrganizationMembership.objects.create(
            organization=other_organization, user=self.user, level=OrganizationMembership.Level.MEMBER
        )
        foreign_role = Role.objects.create(name="Foreign role", organization=other_organization)
        RoleMembership.objects.create(role=foreign_role, user=self.user, organization_member=other_membership)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            role=foreign_role,
            access_level=role_level,
        )

        assert self.permissions().current_team.effective_membership_level == expected_level

    @parameterized.expand(
        [
            ("denial", "none", "member", OrganizationMembership.Level.MEMBER),
            ("grant", "admin", "none", None),
        ]
    )
    def test_member_rule_from_another_organization_is_ignored(self, _name, member_level, default_level, expected_level):
        # Same as above for the member arm: nothing scopes `organization_member` on an AccessControl
        # row to the project's organization, so a rule can name a membership the user holds elsewhere
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self._grant_project_access(default_level)

        other_organization = Organization.objects.create(name="Other organization")
        other_membership = OrganizationMembership.objects.create(
            organization=other_organization, user=self.user, level=OrganizationMembership.Level.MEMBER
        )
        self._grant_project_access(member_level, member=other_membership)

        assert self.permissions().current_team.effective_membership_level == expected_level

    def test_effective_membership_level_rejects_a_membership_from_another_user(self):
        # Roles are resolved through the UserPermissions principal, so a mismatched membership would
        # mix one user's roles into another user's resolution
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", None)
        other_membership = OrganizationMembership.objects.get(user=other_user, organization=self.organization)

        permissions = self.permissions()
        with self.assertRaises(ValueError):
            permissions.current_team.effective_membership_level_for_parent_membership(
                self.organization, other_membership
            )

    @parameterized.expand(
        [
            ("with_access_control", True),
            ("without_access_control", False),
        ]
    )
    def test_effective_membership_level_caps_organization_owner_at_admin(self, _name, access_control_available):
        # Project access tops out at admin, so OWNER must not leak out of a project-level resolver
        if not access_control_available:
            self.organization.available_product_features = []
            self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

        assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    @parameterized.expand(
        [
            ("denial", "none", None),
            ("grant", "admin", OrganizationMembership.Level.ADMIN),
        ]
    )
    def test_role_rule_applies_through_a_role_membership_without_organization_member(
        self, _name, role_level, expected_level
    ):
        # RoleMembership.organization_member is nullable and legacy rows have it NULL, so resolving
        # roles through that FK drops those rows' rules
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        self._grant_project_access("member")
        self._grant_project_access_via_new_role(role_level, legacy_membership=True)

        assert self.permissions().current_team.effective_membership_level == expected_level

    @parameterized.expand(
        [
            ("member_none_without_default", "none", None, None, None),
            ("member_none_with_admin_default", "none", None, "admin", None),
            ("role_none_without_default", None, "none", None, None),
            ("role_none_with_member_default", None, "none", "member", None),
            ("member_none_role_admin", "none", "admin", None, OrganizationMembership.Level.ADMIN),
            ("member_admin_role_none", "admin", "none", None, OrganizationMembership.Level.ADMIN),
            ("member_none_role_member", "none", "member", "none", OrganizationMembership.Level.MEMBER),
        ]
    )
    def test_team_effective_membership_level_explicit_denial(
        self, _name, member_level, role_level, default_level, expected_level
    ):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        if default_level is not None:
            self._grant_project_access(default_level)
        if member_level is not None:
            self._grant_project_access(member_level, member=self.organization_membership)
        if role_level is not None:
            self._grant_project_access_via_new_role(role_level)

        assert self.permissions().current_team.effective_membership_level == expected_level

    def test_team_effective_membership_level_stale_role_denial_inert_without_role_based_access(self):
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        self._grant_project_access_via_new_role("none")

        assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    @parameterized.expand([("member_specific", True), ("role_based", False)])
    def test_team_denied_by_explicit_rule_is_not_visible(self, _name, via_member):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        if via_member:
            self._grant_project_access("none", member=self.organization_membership)
        else:
            self._grant_project_access_via_new_role("none")

        assert self.team.id not in self.permissions().team_ids_visible_for_user
        assert self.team.project_id not in self.permissions().project_ids_visible_for_user

    @parameterized.expand([("member_specific", True), ("role_based", False)])
    def test_team_effective_membership_level_agrees_with_user_access_control(self, _name, via_member):
        from products.access_control.backend.facade.user_access_control import UserAccessControl

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # An open project default, so only the explicit denial can deny
        self._grant_project_access("admin")
        if via_member:
            self._grant_project_access("none", member=self.organization_membership)
        else:
            self._grant_project_access_via_new_role("none")

        # `get_user_access_level` is what `check_access_level_for_object` gates project API access
        # on, so an effective membership level here must not contradict it
        user_access_control = UserAccessControl(user=self.user, team=self.team)
        assert user_access_control.get_user_access_level(self.team) == "none"
        assert self.permissions().current_team.effective_membership_level is None


class TestUserDashboardPermissions(BaseTest, WithPermissionsBase):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.dashboard = Dashboard.objects.create(team=self.team)

    def dashboard_permissions(self):
        return self.permissions().dashboard(self.dashboard)

    def test_dashboard_effective_restriction_level(self):
        assert (
            self.dashboard_permissions().effective_restriction_level
            == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )

    def test_dashboard_effective_restriction_level_explicit(self):
        self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.dashboard.save()

        assert (
            self.dashboard_permissions().effective_restriction_level
            == Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )

    def test_dashboard_effective_restriction_level_when_feature_not_available(self):
        self.organization.available_product_features = []
        self.organization.save()

        self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.dashboard.save()

        assert (
            self.dashboard_permissions().effective_restriction_level
            == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )

    def test_dashboard_can_restrict(self):
        from products.access_control.backend.models.access_control import AccessControl

        # Explicitly set project default access to member level so the user
        # doesn't get the implicit admin default
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="member",
        )
        assert not self.dashboard_permissions().can_restrict

    def test_dashboard_can_restrict_as_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        assert self.dashboard_permissions().can_restrict

    def test_dashboard_can_restrict_as_creator(self):
        self.dashboard.created_by = self.user
        self.dashboard.save()

        assert self.dashboard_permissions().can_restrict

    def test_dashboard_effective_privilege_level_when_everyone_can_edit(self):
        self.dashboard.restriction_level = Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        self.dashboard.save()

        assert self.dashboard_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT

    def test_dashboard_effective_privilege_level_when_collaborators_can_edit(self):
        from products.access_control.backend.models.access_control import AccessControl

        self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.dashboard.save()

        # Explicitly set project default access to member level so the user
        # doesn't get the implicit admin default (which would grant can_restrict)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="member",
        )

        assert self.dashboard_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_VIEW

    def test_dashboard_effective_privilege_level_priviledged(self):
        self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.dashboard.save()

        DashboardPrivilege.objects.create(
            user=self.user,
            dashboard=self.dashboard,
            level=Dashboard.PrivilegeLevel.CAN_EDIT,
        )

        assert self.dashboard_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT

    def test_dashboard_effective_privilege_level_creator(self):
        self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.dashboard.save()
        self.dashboard.created_by = self.user
        self.dashboard.save()

        assert self.dashboard_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT

    def test_dashboard_can_edit_when_everyone_can(self):
        self.dashboard.restriction_level = Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        self.dashboard.save()

        assert self.dashboard_permissions().can_edit

    def test_dashboard_can_edit_not_collaborator(self):
        from products.access_control.backend.models.access_control import AccessControl

        self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.dashboard.save()

        # Explicitly set project default access to member level so the user
        # doesn't get the implicit admin default (which would grant can_restrict -> can_edit)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="member",
        )

        assert not self.dashboard_permissions().can_edit

    def test_dashboard_can_edit_creator(self):
        self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.dashboard.save()
        self.dashboard.created_by = self.user
        self.dashboard.save()

        assert self.dashboard_permissions().can_edit

    def test_dashboard_can_edit_priviledged(self):
        self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.dashboard.save()

        DashboardPrivilege.objects.create(
            user=self.user,
            dashboard=self.dashboard,
            level=Dashboard.PrivilegeLevel.CAN_EDIT,
        )

        assert self.dashboard_permissions().can_edit


class TestUserInsightPermissions(BaseTest, WithPermissionsBase):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()

        self.dashboard1 = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        self.dashboard2 = Dashboard.objects.create(team=self.team)
        self.insight = Insight.objects.create(team=self.team)
        self.tile1 = DashboardTile.objects.create(dashboard=self.dashboard1, insight=self.insight)
        self.tile2 = DashboardTile.objects.create(dashboard=self.dashboard2, insight=self.insight)

    def insight_permissions(self):
        return self.permissions().insight(self.insight)

    def test_effective_restriction_level_limited(self):
        assert (
            self.insight_permissions().effective_restriction_level
            == Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        )

    def test_effective_restriction_level_all_allow(self):
        Dashboard.objects.all().update(restriction_level=Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)

        assert (
            self.insight_permissions().effective_restriction_level
            == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )

    def test_effective_restriction_level_with_no_dashboards(self):
        DashboardTile.objects.all().delete()

        assert (
            self.insight_permissions().effective_restriction_level
            == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )

    def test_effective_restriction_level_with_no_permissioning(self):
        self.organization.available_product_features = []
        self.organization.save()

        assert (
            self.insight_permissions().effective_restriction_level
            == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )

    def test_effective_privilege_level_all_limited(self):
        from products.access_control.backend.models.access_control import AccessControl

        Dashboard.objects.all().update(restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT)

        # Explicitly set project default access to member level so the user
        # doesn't get the implicit admin default (which would grant can_restrict -> can_edit)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="member",
        )

        assert self.insight_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_VIEW

    def test_effective_privilege_level_some_limited(self):
        assert self.insight_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT

    def test_effective_privilege_level_all_limited_as_collaborator(self):
        Dashboard.objects.all().update(restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT)
        self.dashboard1.created_by = self.user
        self.dashboard1.save()

        assert self.insight_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT

    def test_effective_privilege_level_with_no_dashboards(self):
        DashboardTile.objects.all().delete()

        assert self.insight_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT


class TestUserPermissionsEfficiency(BaseTest, WithPermissionsBase):
    def test_dashboard_efficiency(self):
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        insights, tiles = [], []
        for _ in range(10):
            insight = Insight.objects.create(team=self.team)
            tile = DashboardTile.objects.create(dashboard=dashboard, insight=insight)
            insights.append(insight)
            tiles.append(tile)

        user_permissions = self.permissions()
        user_permissions.set_preloaded_dashboard_tiles(tiles)

        with self.assertNumQueries(4):
            assert user_permissions.current_team.effective_membership_level is not None
            assert user_permissions.dashboard(dashboard).effective_restriction_level is not None
            assert user_permissions.dashboard(dashboard).can_restrict is not None
            assert user_permissions.dashboard(dashboard).effective_privilege_level is not None
            assert user_permissions.dashboard(dashboard).can_edit is not None

            for insight in insights:
                assert user_permissions.insight(insight).effective_restriction_level is not None
                assert user_permissions.insight(insight).effective_privilege_level is not None
