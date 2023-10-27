from ee.models.dashboard_privilege import DashboardPrivilege
from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.constants import AvailableFeature
from posthog.models.dashboard import Dashboard
from posthog.models.dashboard_tile import DashboardTile
from posthog.models.insight import Insight
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.test.base import BaseTest
from posthog.user_permissions import UserPermissions


class WithPermissionsBase:
    user: User
    team: Team

    def permissions(self):
        return UserPermissions(user=self.user, team=self.team)


class TestUserTeamPermissions(BaseTest, WithPermissionsBase):
    def setUp(self):
        super().setUp()
        self.organization.available_features = [
            AvailableFeature.PROJECT_BASED_PERMISSIONING,
        ]
        self.organization.save()

    def test_team_effective_membership_level(self):
        with self.assertNumQueries(1):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.MEMBER

    def test_team_effective_membership_level_updated(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        with self.assertNumQueries(1):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_effective_membership_level_does_not_belong(self):
        self.organization_membership.delete()

        permissions = UserPermissions(user=self.user)
        with self.assertNumQueries(1):
            assert permissions.team(self.team).effective_membership_level is None

    def test_team_effective_membership_level_with_explicit_membership_returns_current_level(self):
        self.team.access_control = True
        self.team.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        with self.assertNumQueries(2):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_effective_membership_level_with_member(self):
        self.team.access_control = True
        self.team.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        with self.assertNumQueries(2):
            assert self.permissions().current_team.effective_membership_level is None

    def test_team_effective_membership_level_with_explicit_membership_returns_explicit_membership(self):
        self.team.access_control = True
        self.team.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        ExplicitTeamMembership.objects.create(
            team=self.team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.ADMIN,
        )

        with self.assertNumQueries(2):
            assert self.permissions().current_team.effective_membership_level == OrganizationMembership.Level.ADMIN

    def test_team_ids_visible_for_user(self):
        assert self.permissions().team_ids_visible_for_user == [self.team.pk]

    def test_team_ids_visible_for_user_no_explicit_permissions(self):
        self.team.access_control = True
        self.team.save()

        assert self.permissions().team_ids_visible_for_user == []

    def test_team_ids_visible_for_user_explicit_permission(self):
        self.team.access_control = True
        self.team.save()

        ExplicitTeamMembership.objects.create(
            team=self.team,
            parent_membership=self.organization_membership,
            level=ExplicitTeamMembership.Level.ADMIN,
        )

        assert self.permissions().team_ids_visible_for_user == [self.team.pk]


class TestUserDashboardPermissions(BaseTest, WithPermissionsBase):
    def setUp(self):
        super().setUp()
        self.organization.available_features = [AvailableFeature.DASHBOARD_PERMISSIONING]
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
        self.organization.available_features = []
        self.organization.save()

        self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.dashboard.save()

        assert (
            self.dashboard_permissions().effective_restriction_level
            == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )

    def test_dashboard_can_restrict(self):
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
        self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.dashboard.save()

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
        self.dashboard.restriction_level = Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT
        self.dashboard.save()

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
        self.organization.available_features = [AvailableFeature.DASHBOARD_PERMISSIONING]
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
        self.organization.available_features = []
        self.organization.save()

        assert (
            self.insight_permissions().effective_restriction_level
            == Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT
        )

    def test_effective_privilege_level_all_limited(self):
        Dashboard.objects.all().update(restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT)

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
        self.organization.available_features = [
            AvailableFeature.PROJECT_BASED_PERMISSIONING,
            AvailableFeature.DASHBOARD_PERMISSIONING,
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

        with self.assertNumQueries(3):
            assert user_permissions.current_team.effective_membership_level is not None
            assert user_permissions.dashboard(dashboard).effective_restriction_level is not None
            assert user_permissions.dashboard(dashboard).can_restrict is not None
            assert user_permissions.dashboard(dashboard).effective_privilege_level is not None
            assert user_permissions.dashboard(dashboard).can_edit is not None

            for insight in insights:
                assert user_permissions.insight(insight).effective_restriction_level is not None
                assert user_permissions.insight(insight).effective_privilege_level is not None

    def test_team_lookup_efficiency(self):
        user = User.objects.create(email="test2@posthog.com")
        models = []
        for _ in range(10):
            organization, membership, team = Organization.objects.bootstrap(
                user=user, team_fields={"access_control": True}
            )
            membership.level = OrganizationMembership.Level.ADMIN  # type: ignore
            membership.save()  # type: ignore

            organization.available_features = [AvailableFeature.PROJECT_BASED_PERMISSIONING]
            organization.save()

            models.append((organization, membership, team))

        user_permissions = UserPermissions(user)
        with self.assertNumQueries(3):
            assert len(user_permissions.team_ids_visible_for_user) == 10

            for _, _, team in models:
                assert user_permissions.team(team).effective_membership_level == OrganizationMembership.Level.ADMIN
