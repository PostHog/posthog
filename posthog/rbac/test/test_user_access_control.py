import pytest
from posthog.constants import AvailableFeature
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.test.base import BaseTest


try:
    from ee.models.rbac.access_control import AccessControl
    from ee.models.rbac.role import Role, RoleMembership
except ImportError:
    pass


@pytest.mark.ee
class TestUserTeamPermissions(BaseTest):
    user_access_control: UserAccessControl

    def _create_access_control(
        self, resource="project", resource_id=None, access_level="admin", organization_member=None, team=None, role=None
    ):
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id or self.team.id,
            access_level=access_level,
            organization_member=organization_member,
            role=role,
        )

    def setUp(self):
        super().setUp()
        self.organization.available_features = [
            AvailableFeature.PROJECT_BASED_PERMISSIONING,
            AvailableFeature.ROLE_BASED_ACCESS,
        ]
        self.organization.save()

        self.role_a = Role.objects.create(name="Engineers", organization=self.organization)
        self.role_b = Role.objects.create(name="Administrators", organization=self.organization)

        RoleMembership.objects.create(user=self.user, role=self.role_a)
        self.user_access_control = UserAccessControl(self.user, self.team)

        self.other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "testtest")
        RoleMembership.objects.create(user=self.other_user, role=self.role_b)
        self.other_user_access_control = UserAccessControl(self.other_user, self.team)

        self.user_with_no_role = User.objects.create_and_join(self.organization, "norole@posthog.com", "testtest")
        self.user_with_no_role_access_control = UserAccessControl(self.user_with_no_role, self.team)

    def test_ac_object_default_response_without_available_feature(self):
        self.organization.available_features = []
        self.organization.save()

        assert self.user_access_control.access_control_for_object(self.team) is None
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is None
        assert self.other_user_access_control.access_control_for_object(self.team) is None
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is None

    def test_ac_object_default_response(self):
        assert self.user_access_control.access_control_for_object(self.team).access_level == "member"
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.other_user_access_control.access_control_for_object(self.team).access_level == "member"
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is False

    def test_ac_object_user_access_control(self):
        ac = self._create_access_control(
            resource="project",
            resource_id=str(self.team.id),
            access_level="admin",
            # context
            organization_member=self.organization_membership,
        )

        assert self.user_access_control.access_control_for_object(self.team) == ac
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is True
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is False

        ac.access_level = "member"
        ac.save()

        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.user_access_control.check_access_level_for_object(self.team, "member") is True
        assert (
            self.other_user_access_control.check_access_level_for_object(self.team, "member")
            is True  # This is the default
        )  # Fix this - need to load all access controls...

    def test_ac_object_project_access_control(self):
        # Setup no access by default
        ac = self._create_access_control(access_level="none")

        assert self.user_access_control.access_control_for_object(self.team) == ac
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is False

        ac.access_level = "member"
        ac.save()

        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.user_access_control.check_access_level_for_object(self.team, "member") is True
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.other_user_access_control.check_access_level_for_object(self.team, "member") is True

        ac.access_level = "admin"
        ac.save()

        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is True
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is True

    def test_ac_object_role_access_control(self):
        ac = self._create_access_control(access_level="admin", role=self.role_a)

        assert self.user_access_control.access_control_for_object(self.team) == ac
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is True
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.user_with_no_role_access_control.check_access_level_for_object(self.team, "admin") is False

        ac.access_level = "member"
        ac.save()

        # Make the default access level none
        self._create_access_control(access_level="none")

        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.user_access_control.check_access_level_for_object(self.team, "member") is True
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.other_user_access_control.check_access_level_for_object(self.team, "member") is False
        assert self.user_with_no_role_access_control.check_access_level_for_object(self.team, "admin") is False

    def test_ac_object_mixed_access_controls(self):
        # No access by default
        ac_project = self._create_access_control(access_level="none")
        # Enroll self.user as member
        ac_user = self._create_access_control(access_level="member", organization_member=self.organization_membership)
        # Enroll role_a as admin
        ac_role = self._create_access_control(access_level="admin", role=self.role_a)  # The highest AC
        # Enroll role_b as member
        ac_role_2 = self._create_access_control(access_level="member", role=self.role_b)
        # Enroll self.user in both roles
        RoleMembership.objects.create(user=self.user, role=self.role_b)

        # Create an unrelated access control for self.user
        self._create_access_control(
            resource_id="something else", access_level="admin", organization_member=self.organization_membership
        )

        matching_acs = list(self.user_access_control._access_controls_for_object(self.team))
        assert len(matching_acs) == 4
        assert ac_project in matching_acs
        assert ac_user in matching_acs
        assert ac_role in matching_acs
        assert ac_role_2 in matching_acs
        # the matching one should be the highest level
        assert self.user_access_control.access_control_for_object(self.team) == ac_role


#     def test_team_effective_membership_level(self):
#         with self.assertNumQueries(1):
#             assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.MEMBER

#     def test_team_effective_membership_level_updated(self):
#         self.organization_membership.level = OrganizationMembership.Level.ADMIN
#         self.organization_membership.save()

#         with self.assertNumQueries(1):
#             assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

#     def test_team_effective_membership_level_does_not_belong(self):
#         self.organization_membership.delete()

#         permissions = UserPermissions(user=self.user)
#         with self.assertNumQueries(1):
#             assert permissions.team(self.team).effective_membership_level is None

#     def test_team_effective_membership_level_membership_isolation(self):
#         self.team.access_control = True
#         self.team.save()
#         ExplicitTeamMembership.objects.create(
#             team=self.team,
#             parent_membership=self.organization_membership,
#         )
#         forbidden_team = Team.objects.create(
#             organization=self.organization,
#             name="FORBIDDEN",
#             access_control=True,
#         )
#         permissions = UserPermissions(user=self.user)
#         with self.assertNumQueries(2):
#             assert permissions.team(forbidden_team).effective_membership_level is None

#     def test_team_effective_membership_level_with_explicit_membership_returns_current_level(self):
#         self.team.access_control = True
#         self.team.save()
#         self.organization_membership.level = OrganizationMembership.Level.ADMIN
#         self.organization_membership.save()

#         with self.assertNumQueries(2):
#             assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

#     def test_team_effective_membership_level_with_member(self):
#         self.team.access_control = True
#         self.team.save()
#         self.organization_membership.level = OrganizationMembership.Level.MEMBER
#         self.organization_membership.save()

#         with self.assertNumQueries(2):
#             assert self.permissions().current_team.effective_membership_level is None

#     def test_team_effective_membership_level_with_explicit_membership_returns_explicit_membership(self):
#         self.team.access_control = True
#         self.team.save()
#         self.organization_membership.level = OrganizationMembership.Level.MEMBER
#         self.organization_membership.save()

#         ExplicitTeamMembership.objects.create(
#             team=self.team,
#             parent_membership=self.organization_membership,
#             level=ExplicitTeamMembership.Level.ADMIN,
#         )

#         with self.assertNumQueries(2):
#             assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

#     def test_team_ids_visible_for_user(self):
#         assert self.permissions().team_ids_visible_for_user == [self.team.pk]

#     def test_team_ids_visible_for_user_no_explicit_permissions(self):
#         self.team.access_control = True
#         self.team.save()

#         assert self.permissions().team_ids_visible_for_user == []

#     def test_team_ids_visible_for_user_explicit_permission(self):
#         self.team.access_control = True
#         self.team.save()

#         ExplicitTeamMembership.objects.create(
#             team=self.team,
#             parent_membership=self.organization_membership,
#             level=ExplicitTeamMembership.Level.ADMIN,
#         )

#         assert self.permissions().team_ids_visible_for_user == [self.team.pk]


# class TestUserDashboardPermissions(BaseTest, WithPermissionsBase):
#     def setUp(self):
#         super().setUp()
#         self.organization.available_features = [AvailableFeature.ADVANCED_PERMISSIONS]
#         self.organization.save()
#         self.dashboard = Dashboard.objects.create(team=self.team)

#     def dashboard_permissions(self):
#         return self.permissions().dashboard(self.dashboard)

#     def test_dashboard_effective_restriction_level(self):
#         assert (
#             self.dashboard_permissions().effective_restriction_level
#             == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
#         )

#     def test_dashboard_effective_restriction_level_explicit(self):
#         self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
#         self.dashboard.save()

#         assert (
#             self.dashboard_permissions().effective_restriction_level
#             == Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
#         )

#     def test_dashboard_effective_restriction_level_when_feature_not_available(self):
#         self.organization.available_features = []
#         self.organization.save()

#         self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
#         self.dashboard.save()

#         assert (
#             self.dashboard_permissions().effective_restriction_level
#             == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
#         )

#     def test_dashboard_can_restrict(self):
#         assert not self.dashboard_permissions().can_restrict

#     def test_dashboard_can_restrict_as_admin(self):
#         self.organization_membership.level = OrganizationMembership.Level.ADMIN
#         self.organization_membership.save()

#         assert self.dashboard_permissions().can_restrict

#     def test_dashboard_can_restrict_as_creator(self):
#         self.dashboard.created_by = self.user
#         self.dashboard.save()

#         assert self.dashboard_permissions().can_restrict

#     def test_dashboard_effective_privilege_level_when_everyone_can_edit(self):
#         self.dashboard.restriction_level = Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
#         self.dashboard.save()

#         assert self.dashboard_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT

#     def test_dashboard_effective_privilege_level_when_collaborators_can_edit(self):
#         self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
#         self.dashboard.save()

#         assert self.dashboard_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_VIEW

#     def test_dashboard_effective_privilege_level_priviledged(self):
#         self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
#         self.dashboard.save()

#         DashboardPrivilege.objects.create(
#             user=self.user,
#             dashboard=self.dashboard,
#             level=Dashboard.PrivilegeLevel.CAN_EDIT,
#         )

#         assert self.dashboard_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT

#     def test_dashboard_effective_privilege_level_creator(self):
#         self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
#         self.dashboard.save()
#         self.dashboard.created_by = self.user
#         self.dashboard.save()

#         assert self.dashboard_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT

#     def test_dashboard_can_edit_when_everyone_can(self):
#         self.dashboard.restriction_level = Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
#         self.dashboard.save()

#         assert self.dashboard_permissions().can_edit

#     def test_dashboard_can_edit_not_collaborator(self):
#         self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
#         self.dashboard.save()

#         assert not self.dashboard_permissions().can_edit

#     def test_dashboard_can_edit_creator(self):
#         self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
#         self.dashboard.save()
#         self.dashboard.created_by = self.user
#         self.dashboard.save()

#         assert self.dashboard_permissions().can_edit

#     def test_dashboard_can_edit_priviledged(self):
#         self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
#         self.dashboard.save()

#         DashboardPrivilege.objects.create(
#             user=self.user,
#             dashboard=self.dashboard,
#             level=Dashboard.PrivilegeLevel.CAN_EDIT,
#         )

#         assert self.dashboard_permissions().can_edit


# class TestUserInsightPermissions(BaseTest, WithPermissionsBase):
#     def setUp(self):
#         super().setUp()
#         self.organization.available_features = [AvailableFeature.ADVANCED_PERMISSIONS]
#         self.organization.save()

#         self.dashboard1 = Dashboard.objects.create(
#             team=self.team,
#             restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
#         )
#         self.dashboard2 = Dashboard.objects.create(team=self.team)
#         self.insight = Insight.objects.create(team=self.team)
#         self.tile1 = DashboardTile.objects.create(dashboard=self.dashboard1, insight=self.insight)
#         self.tile2 = DashboardTile.objects.create(dashboard=self.dashboard2, insight=self.insight)

#     def insight_permissions(self):
#         return self.permissions().insight(self.insight)

#     def test_effective_restriction_level_limited(self):
#         assert (
#             self.insight_permissions().effective_restriction_level
#             == Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
#         )

#     def test_effective_restriction_level_all_allow(self):
#         Dashboard.objects.all().update(restriction_level=Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT)

#         assert (
#             self.insight_permissions().effective_restriction_level
#             == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
#         )

#     def test_effective_restriction_level_with_no_dashboards(self):
#         DashboardTile.objects.all().delete()

#         assert (
#             self.insight_permissions().effective_restriction_level
#             == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
#         )

#     def test_effective_restriction_level_with_no_permissioning(self):
#         self.organization.available_features = []
#         self.organization.save()

#         assert (
#             self.insight_permissions().effective_restriction_level
#             == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
#         )

#     def test_effective_privilege_level_all_limited(self):
#         Dashboard.objects.all().update(restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT)

#         assert self.insight_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_VIEW

#     def test_effective_privilege_level_some_limited(self):
#         assert self.insight_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT

#     def test_effective_privilege_level_all_limited_as_collaborator(self):
#         Dashboard.objects.all().update(restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT)
#         self.dashboard1.created_by = self.user
#         self.dashboard1.save()

#         assert self.insight_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT

#     def test_effective_privilege_level_with_no_dashboards(self):
#         DashboardTile.objects.all().delete()

#         assert self.insight_permissions().effective_privilege_level == Dashboard.PrivilegeLevel.CAN_EDIT


# class TestUserPermissionsEfficiency(BaseTest, WithPermissionsBase):
#     def test_dashboard_efficiency(self):
#         self.organization.available_features = [
#             AvailableFeature.PROJECT_BASED_PERMISSIONING,
#             AvailableFeature.ADVANCED_PERMISSIONS,
#         ]
#         self.organization.save()

#         dashboard = Dashboard.objects.create(
#             team=self.team,
#             restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
#         )
#         insights, tiles = [], []
#         for _ in range(10):
#             insight = Insight.objects.create(team=self.team)
#             tile = DashboardTile.objects.create(dashboard=dashboard, insight=insight)
#             insights.append(insight)
#             tiles.append(tile)

#         user_permissions = self.permissions()
#         user_permissions.set_preloaded_dashboard_tiles(tiles)

#         with self.assertNumQueries(3):
#             assert user_permissions.current_team.effective_membership_level is not None
#             assert user_permissions.dashboard(dashboard).effective_restriction_level is not None
#             assert user_permissions.dashboard(dashboard).can_restrict is not None
#             assert user_permissions.dashboard(dashboard).effective_privilege_level is not None
#             assert user_permissions.dashboard(dashboard).can_edit is not None

#             for insight in insights:
#                 assert user_permissions.insight(insight).effective_restriction_level is not None
#                 assert user_permissions.insight(insight).effective_privilege_level is not None

#     def test_team_lookup_efficiency(self):
#         user = User.objects.create(email="test2@posthog.com", distinct_id="test2")
#         models = []
#         for _ in range(10):
#             organization, membership, team = Organization.objects.bootstrap(
#                 user=user, team_fields={"access_control": True}
#             )
#             membership.level = OrganizationMembership.Level.ADMIN  # type: ignore
#             membership.save()  # type: ignore

#             organization.available_features = [AvailableFeature.PROJECT_BASED_PERMISSIONING]
#             organization.save()

#             models.append((organization, membership, team))

#         user_permissions = UserPermissions(user)
#         with self.assertNumQueries(3):
#             assert len(user_permissions.team_ids_visible_for_user) == 10

#             for _, _, team in models:
#                 assert user_permissions.team(team).effective_membership_level == OrganizationMembership.Level.ADMIN
