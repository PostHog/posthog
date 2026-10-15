import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rbac.migrations.rbac_dashboard_migration import rbac_dashboard_access_control_migration

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.dashboards.backend.models.dashboard import Dashboard

from ee.models.dashboard_privilege import DashboardPrivilege


@pytest.mark.ee
class TestRBACDashboardMigration(BaseTest):
    def setUp(self):
        super().setUp()
        # Enable access control for the organization
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            },
        ]
        self.organization.save()

        # Create additional users and team members
        self.user2 = User.objects.create_and_join(self.organization, "user2@posthog.com", "password123")
        self.user3 = User.objects.create_and_join(self.organization, "user3@posthog.com", "password123")

        # Get organization memberships
        self.user1_membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        self.user2_membership = OrganizationMembership.objects.get(user=self.user2, organization=self.organization)
        self.user3_membership = OrganizationMembership.objects.get(user=self.user3, organization=self.organization)

    def test_migrate_dashboard_with_restriction_level_37_no_privileges(self):
        """Test migrating a dashboard with restriction level 37 but no existing privileges"""
        # Create a dashboard with restriction level 37 (ONLY_COLLABORATORS_CAN_EDIT)
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Restricted Dashboard",
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        # Verify initial state
        self.assertEqual(dashboard.restriction_level, Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT)
        self.assertFalse(AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard.id)).exists())

        # Run migration
        rbac_dashboard_access_control_migration(self.organization.id)

        # Reload dashboard from database
        dashboard.refresh_from_db()

        # Verify dashboard restriction level was updated
        self.assertEqual(dashboard.restriction_level, Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)

        # Verify default access control was created
        access_controls = AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard.id))
        self.assertEqual(access_controls.count(), 1)

        default_ac = access_controls.first()
        assert default_ac is not None
        self.assertEqual(default_ac.access_level, "viewer")
        self.assertEqual(default_ac.team_id, self.team.id)
        self.assertIsNone(default_ac.organization_member)
        self.assertIsNone(default_ac.role)

    def test_migrate_dashboard_with_restriction_level_37_and_privileges(self):
        """Test migrating a dashboard with restriction level 37 and existing dashboard privileges"""
        # Create a dashboard with restriction level 37
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Restricted Dashboard with Privileges",
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        # Create dashboard privileges for users
        DashboardPrivilege.objects.create(
            dashboard=dashboard,
            user=self.user2,
            level=Dashboard.PrivilegeLevel.CAN_EDIT,
        )
        DashboardPrivilege.objects.create(
            dashboard=dashboard,
            user=self.user3,
            level=Dashboard.PrivilegeLevel.CAN_VIEW,
        )

        # Verify initial state
        self.assertEqual(DashboardPrivilege.objects.filter(dashboard=dashboard).count(), 2)

        # Run migration
        rbac_dashboard_access_control_migration(self.organization.id)

        # Reload dashboard from database
        dashboard.refresh_from_db()

        # Verify dashboard restriction level was updated
        self.assertEqual(dashboard.restriction_level, Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)

        # Verify access controls were created
        access_controls = AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard.id))
        self.assertEqual(access_controls.count(), 3)  # 1 default + 2 user privileges

        # Verify default access control
        default_ac = access_controls.filter(organization_member=None, role=None).first()
        assert default_ac is not None
        self.assertEqual(default_ac.access_level, "viewer")

        # Verify user-specific access controls
        user2_ac = access_controls.filter(organization_member=self.user2_membership).first()
        assert user2_ac is not None
        self.assertEqual(user2_ac.access_level, "editor")

        user3_ac = access_controls.filter(organization_member=self.user3_membership).first()
        assert user3_ac is not None
        self.assertEqual(user3_ac.access_level, "editor")  # All privileges become "editor"

        # Verify original privileges were deleted
        self.assertEqual(DashboardPrivilege.objects.filter(dashboard=dashboard).count(), 0)

    def test_migrate_dashboard_with_restriction_level_21_ignored(self):
        """Test that dashboards with restriction level 21 are ignored"""
        # Create a dashboard with restriction level 21 (EVERYONE_IN_PROJECT_CAN_EDIT)
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Unrestricted Dashboard",
            restriction_level=Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
        )

        # Run migration
        rbac_dashboard_access_control_migration(self.organization.id)

        # Reload dashboard from database
        dashboard.refresh_from_db()

        # Verify dashboard restriction level was not changed
        self.assertEqual(dashboard.restriction_level, Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)

        # Verify no access controls were created
        self.assertFalse(AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard.id)).exists())

    def test_migration_handles_user_without_organization_membership(self):
        """Test that migration handles users without organization membership gracefully"""
        # Create a dashboard with restriction level 37
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Dashboard with Invalid User",
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        # Create a user without organization membership
        orphaned_user = User.objects.create(email="orphaned@example.com", password="password123")

        # Create a dashboard privilege for the orphaned user
        DashboardPrivilege.objects.create(
            dashboard=dashboard,
            user=orphaned_user,
            level=Dashboard.PrivilegeLevel.CAN_EDIT,
        )

        # Run migration (should not raise exception)
        rbac_dashboard_access_control_migration(self.organization.id)

        # Reload dashboard from database
        dashboard.refresh_from_db()

        # Verify dashboard was still migrated
        self.assertEqual(dashboard.restriction_level, Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)

        # Verify default access control was created
        default_ac = AccessControl.objects.filter(
            resource="dashboard", resource_id=str(dashboard.id), organization_member=None, role=None
        ).first()
        assert default_ac is not None
        self.assertEqual(default_ac.access_level, "viewer")

        # Verify no access control was created for the orphaned user
        self.assertFalse(
            AccessControl.objects.filter(
                resource="dashboard", resource_id=str(dashboard.id), organization_member__user=orphaned_user
            ).exists()
        )

        # The original privilege should NOT be deleted since we couldn't find org membership
        # This is correct behavior - we skip processing for orphaned users
        orphaned_privilege_count = DashboardPrivilege.objects.filter(user=orphaned_user).count()
        self.assertEqual(orphaned_privilege_count, 1)  # Should still exist

    def test_migration_completes_when_access_control_already_exists(self):
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Dashboard with Existing Access Control",
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        existing_ac = AccessControl.objects.create(
            team_id=self.team.id,
            access_level="manager",
            resource="dashboard",
            resource_id=str(dashboard.id),
            organization_member=self.user1_membership,
        )
        default_ac = AccessControl.objects.create(
            team_id=self.team.id,
            access_level="invalid",
            resource="dashboard",
            resource_id=str(dashboard.id),
        )
        member_ac = AccessControl.objects.create(
            team_id=self.team.id,
            access_level="invalid",
            resource="dashboard",
            resource_id=str(dashboard.id),
            organization_member=self.user2_membership,
        )
        DashboardPrivilege.objects.create(
            dashboard=dashboard,
            user=self.user2,
            level=Dashboard.PrivilegeLevel.CAN_EDIT,
        )

        rbac_dashboard_access_control_migration(self.organization.id)

        dashboard.refresh_from_db()
        self.assertEqual(dashboard.restriction_level, Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)
        self.assertEqual(AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard.id)).count(), 3)
        default_ac.refresh_from_db()
        self.assertEqual(default_ac.access_level, "viewer")
        member_ac.refresh_from_db()
        self.assertEqual(member_ac.access_level, "editor")
        self.assertTrue(AccessControl.objects.filter(id=existing_ac.id).exists())
        self.assertFalse(DashboardPrivilege.objects.filter(dashboard=dashboard).exists())

        rbac_dashboard_access_control_migration(self.organization.id)

        self.assertEqual(AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard.id)).count(), 3)

    def test_migration_preserves_existing_access_control_denials_and_viewers(self):
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Dashboard with existing restrictions",
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        default_access = AccessControl.objects.create(
            team_id=self.team.id,
            access_level="none",
            resource="dashboard",
            resource_id=str(dashboard.id),
        )
        member_access = AccessControl.objects.create(
            team_id=self.team.id,
            access_level="viewer",
            resource="dashboard",
            resource_id=str(dashboard.id),
            organization_member=self.user2_membership,
        )
        DashboardPrivilege.objects.create(
            dashboard=dashboard,
            user=self.user2,
            level=Dashboard.PrivilegeLevel.CAN_EDIT,
        )

        rbac_dashboard_access_control_migration(self.organization.id)

        dashboard.refresh_from_db()
        default_access.refresh_from_db()
        member_access.refresh_from_db()
        self.assertEqual(dashboard.restriction_level, Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)
        self.assertEqual(default_access.access_level, "none")
        self.assertEqual(member_access.access_level, "viewer")
        self.assertFalse(DashboardPrivilege.objects.filter(dashboard=dashboard).exists())

    @parameterized.expand([("viewer",), ("none",)])
    def test_migration_preserves_role_based_dashboard_access(self, role_access_level: str) -> None:
        self.organization.available_product_features = (self.organization.available_product_features or []) + [
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS}
        ]
        self.organization.save()
        role = Role.objects.create(name="Dashboard viewers", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=self.user2,
            organization_member=self.user2_membership,
        )
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Dashboard with role access",
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        AccessControl.objects.create(
            team_id=self.team.id,
            access_level=role_access_level,
            resource="dashboard",
            resource_id=str(dashboard.id),
            role=role,
        )
        DashboardPrivilege.objects.create(
            dashboard=dashboard,
            user=self.user2,
            level=Dashboard.PrivilegeLevel.CAN_EDIT,
        )

        rbac_dashboard_access_control_migration(self.organization.id)

        dashboard.refresh_from_db()
        self.assertEqual(dashboard.restriction_level, Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)
        self.assertFalse(
            AccessControl.objects.filter(
                team_id=self.team.id,
                resource="dashboard",
                resource_id=str(dashboard.id),
                organization_member=self.user2_membership,
                role=None,
            ).exists()
        )
        self.assertFalse(DashboardPrivilege.objects.filter(dashboard=dashboard).exists())
        user_access = UserAccessControl(user=self.user2, team=self.team)
        self.assertFalse(user_access.check_access_level_for_object(dashboard, "editor"))
        self.assertEqual(
            user_access.check_access_level_for_object(dashboard, "viewer"),
            role_access_level == "viewer",
        )

    def test_migration_handles_multiple_teams_in_organization(self):
        """Test that migration works correctly with multiple teams in the organization"""
        # Create another team in the same organization
        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        # Create dashboards in both teams
        dashboard1 = Dashboard.objects.create(
            team=self.team,
            name="Team 1 Dashboard",
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        dashboard2 = Dashboard.objects.create(
            team=team2,
            name="Team 2 Dashboard",
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        # Run migration
        rbac_dashboard_access_control_migration(self.organization.id)

        # Verify both dashboards were migrated
        dashboard1.refresh_from_db()
        dashboard2.refresh_from_db()

        self.assertEqual(dashboard1.restriction_level, Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)
        self.assertEqual(dashboard2.restriction_level, Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)

        # Verify access controls were created for both dashboards
        self.assertTrue(AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard1.id)).exists())
        self.assertTrue(AccessControl.objects.filter(resource="dashboard", resource_id=str(dashboard2.id)).exists())

    def test_migration_handles_organization_not_found(self):
        """Test that migration raises exception for non-existent organization"""
        with self.assertRaises(Organization.DoesNotExist):
            rbac_dashboard_access_control_migration(999999)

    def test_migration_is_idempotent(self):
        """Test that running the migration multiple times doesn't create duplicates"""
        # Create a dashboard with restriction level 37
        dashboard = Dashboard.objects.create(
            team=self.team,
            name="Idempotent Test Dashboard",
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        # Run migration first time
        rbac_dashboard_access_control_migration(self.organization.id)

        # Verify state after first migration
        dashboard.refresh_from_db()
        self.assertEqual(dashboard.restriction_level, Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)
        access_controls_count = AccessControl.objects.filter(
            resource="dashboard", resource_id=str(dashboard.id)
        ).count()
        self.assertEqual(access_controls_count, 1)

        # Run migration second time
        rbac_dashboard_access_control_migration(self.organization.id)

        # Verify no duplicates were created
        final_access_controls_count = AccessControl.objects.filter(
            resource="dashboard", resource_id=str(dashboard.id)
        ).count()
        self.assertEqual(final_access_controls_count, access_controls_count)
