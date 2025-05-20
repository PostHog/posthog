import pytest
from posthog.constants import AvailableFeature
from posthog.models.dashboard import Dashboard
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.file_system.file_system import FileSystem
from posthog.models.organization import Organization
from posthog.rbac.user_access_control import UserAccessControl, UserAccessControlSerializerMixin
from posthog.test.base import BaseTest
from rest_framework import serializers

try:
    from ee.models.rbac.access_control import AccessControl
    from ee.models.rbac.role import Role, RoleMembership
except ImportError:
    pass


class BaseUserAccessControlTest(BaseTest):
    user_access_control: UserAccessControl

    def _create_access_control(
        self, resource="project", resource_id=None, access_level="admin", organization_member=None, team=None, role=None
    ):
        ac, _ = AccessControl.objects.get_or_create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            organization_member=organization_member,
            role=role,
        )

        ac.access_level = access_level
        ac.save()

        return ac

    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ADVANCED_PERMISSIONS,
                "name": AvailableFeature.ADVANCED_PERMISSIONS,
            },
            {
                "key": AvailableFeature.ROLE_BASED_ACCESS,
                "name": AvailableFeature.ROLE_BASED_ACCESS,
            },
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

    def _clear_uac_caches(self):
        self.user_access_control._clear_cache()
        self.other_user_access_control._clear_cache()
        self.user_with_no_role_access_control._clear_cache()


@pytest.mark.ee
class TestUserAccessControl(BaseUserAccessControlTest):
    def test_no_organization_id_passed(self):
        # Create a user without an organization
        user_without_org = User.objects.create(email="no-org@posthog.com", password="testtest")
        user_access_control = UserAccessControl(user_without_org)

        assert user_access_control._organization_membership is None
        assert user_access_control._organization is None
        assert user_access_control._user_role_ids == []

    def test_organization_with_no_project_or_team(self):
        organization = Organization.objects.create(name="No project or team")
        user = User.objects.create_and_join(organization, "no-project-or-team@posthog.com", "testtest")
        user_access_control = UserAccessControl(user, organization_id=organization.id)

        assert user_access_control._organization_membership is not None
        assert user_access_control._organization == organization

    def test_organization_with_no_project_or_team_and_no_organization_id(self):
        organization = Organization.objects.create(name="No project or team")
        user = User.objects.create_and_join(organization, "no-project-or-team@posthog.com", "testtest")
        user_access_control = UserAccessControl(user)

        assert user_access_control._organization_membership is None
        assert user_access_control._organization is None
        assert user_access_control._user_role_ids == []

    def test_without_available_product_features(self):
        self.organization.available_product_features = []
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        assert self.user_access_control.access_level_for_object(self.team) == "admin"
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is True
        assert self.other_user_access_control.access_level_for_object(self.team) == "admin"
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is True
        assert self.user_access_control.access_level_for_resource("project") == "admin"
        assert self.other_user_access_control.access_level_for_resource("project") == "admin"
        assert self.user_access_control.check_can_modify_access_levels_for_object(self.team) is True
        assert self.other_user_access_control.check_can_modify_access_levels_for_object(self.team) is False

    def test_ac_object_default_response(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        assert self.user_access_control.access_level_for_object(self.team) == "admin"
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is True
        assert self.other_user_access_control.access_level_for_object(self.team) == "admin"
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is True
        assert self.user_access_control.access_level_for_resource("project") == "admin"
        assert self.other_user_access_control.access_level_for_resource("project") == "admin"
        assert self.user_access_control.check_can_modify_access_levels_for_object(self.team) is True
        assert self.other_user_access_control.check_can_modify_access_levels_for_object(self.team) is False

    def test_ac_object_user_access_control(self):
        # Setup member access by default
        self._create_access_control(resource_id=self.team.id, access_level="member")
        ac = self._create_access_control(
            resource="project",
            resource_id=str(self.team.id),
            access_level="admin",
            # context
            organization_member=self.organization_membership,
        )

        assert self.user_access_control.access_level_for_object(self.team) == "admin"
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is True
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is False

        ac.access_level = "member"
        ac.save()
        self._clear_uac_caches()

        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.user_access_control.check_access_level_for_object(self.team, "member") is True
        assert (
            self.other_user_access_control.check_access_level_for_object(self.team, "member")
            is True  # This is the default
        )  # Fix this - need to load all access controls...

    def test_ac_object_project_access_control(self):
        # Setup no access by default
        ac = self._create_access_control(resource_id=self.team.id, access_level="none")

        assert self.user_access_control.access_level_for_object(self.team) == "none"
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is False

        ac.access_level = "member"
        ac.save()
        self._clear_uac_caches()

        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.user_access_control.check_access_level_for_object(self.team, "member") is True
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.other_user_access_control.check_access_level_for_object(self.team, "member") is True

        ac.access_level = "admin"
        ac.save()
        self._clear_uac_caches()

        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is True
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is True

    def test_ac_object_role_access_control(self):
        # Setup member access by default
        self._create_access_control(resource_id=self.team.id, access_level="member")
        ac = self._create_access_control(resource_id=self.team.id, access_level="admin", role=self.role_a)

        assert self.user_access_control.access_level_for_object(self.team) == "admin"
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is True
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.user_with_no_role_access_control.check_access_level_for_object(self.team, "admin") is False

        ac.access_level = "member"
        ac.save()
        self._clear_uac_caches()

        # Make the default access level none
        self._create_access_control(resource_id=self.team.id, access_level="none")

        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.user_access_control.check_access_level_for_object(self.team, "member") is True
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is False
        assert self.other_user_access_control.check_access_level_for_object(self.team, "member") is False
        assert self.user_with_no_role_access_control.check_access_level_for_object(self.team, "admin") is False

    def test_ac_object_mixed_access_controls(self):
        # No access by default
        ac_project = self._create_access_control(resource_id=self.team.id, access_level="none")
        # Enroll self.user as member
        ac_user = self._create_access_control(
            resource_id=self.team.id, access_level="member", organization_member=self.organization_membership
        )
        # Enroll role_a as admin
        ac_role = self._create_access_control(
            resource_id=self.team.id, access_level="admin", role=self.role_a
        )  # The highest AC
        # Enroll role_b as member
        ac_role_2 = self._create_access_control(resource_id=self.team.id, access_level="member", role=self.role_b)
        # Enroll self.user in both roles
        RoleMembership.objects.create(user=self.user, role=self.role_b)

        # Create an unrelated access control for self.user
        self._create_access_control(
            resource_id="something else", access_level="admin", organization_member=self.organization_membership
        )

        matching_acs = self.user_access_control._get_access_controls(
            self.user_access_control._access_controls_filters_for_object("project", str(self.team.id))
        )
        assert len(matching_acs) == 4
        assert ac_project in matching_acs
        assert ac_user in matching_acs
        assert ac_role in matching_acs
        assert ac_role_2 in matching_acs
        # the matching one should be the highest level
        assert self.user_access_control.access_level_for_object(self.team) == "admin"

    def test_org_admin_always_has_access(self):
        self._create_access_control(resource_id=self.team.id, access_level="none")
        assert self.other_user_access_control.check_access_level_for_object(self.team, "member") is False
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is False

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        assert self.user_access_control.check_access_level_for_object(self.team, "member") is True
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is True

    def test_leaving_the_org_revokes_access(self):
        self.user.leave(organization=self.organization)
        assert self.user_access_control.check_access_level_for_object(self.team, "member") is False

    def test_filters_project_queryset_based_on_acs(self):
        team2 = Team.objects.create(organization=self.organization)
        team3 = Team.objects.create(organization=self.organization)
        # No default access
        self._create_access_control(resource="project", resource_id=team2.id, access_level="none")
        # No default access
        self._create_access_control(resource="project", resource_id=team3.id, access_level="none")
        # This user access
        self._create_access_control(
            resource="project",
            resource_id=team3.id,
            access_level="member",
            organization_member=self.organization_membership,
        )

        # NOTE: This is different to the API queries as the TeamAndOrgViewsetMixing takes care of filtering out based on the parent org
        filtered_teams = list(
            self.user_access_control.filter_queryset_by_access_level(Team.objects.all()).order_by("id")
        )
        assert [self.team, team3] == filtered_teams

        other_user_filtered_teams = list(
            self.other_user_access_control.filter_queryset_by_access_level(Team.objects.all())
        )
        assert other_user_filtered_teams == [self.team]

    def test_filters_project_queryset_based_on_acs_always_allows_org_admin(self):
        team2 = Team.objects.create(organization=self.organization)
        team3 = Team.objects.create(organization=self.organization)
        # No default access
        self._create_access_control(resource="project", resource_id=team2.id, access_level="none")
        self._create_access_control(resource="project", resource_id=team3.id, access_level="none")

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        filtered_teams = list(
            self.user_access_control.filter_queryset_by_access_level(
                Team.objects.all(), include_all_if_admin=True
            ).order_by("id")
        )
        self.assertListEqual([self.team, team2, team3], filtered_teams)

    def test_organization_access_control(self):
        # A team isn't always available like for organization level routing

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        uac = UserAccessControl(user=self.user, organization_id=self.organization.id)

        assert uac.check_access_level_for_object(self.organization, "member") is True
        assert uac.check_access_level_for_object(self.organization, "admin") is False

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        uac = UserAccessControl(user=self.user, organization_id=self.organization.id)

        assert uac.check_access_level_for_object(self.organization, "admin") is True


class TestUserAccessControlResourceSpecific(BaseUserAccessControlTest):
    """
    Most things are identical between "project"s and other resources, but there are some differences particularly in level names
    """

    def setUp(self):
        super().setUp()

        self.dashboard = Dashboard.objects.create(team=self.team)

    def test_without_available_product_features(self):
        self.organization.available_product_features = []
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        assert self.user_access_control.access_level_for_object(self.dashboard) == "editor"
        assert self.other_user_access_control.access_level_for_object(self.dashboard) == "editor"
        assert self.user_access_control.access_level_for_resource("dashboard") == "editor"
        assert self.other_user_access_control.access_level_for_resource("dashboard") == "editor"

    def test_ac_object_default_response(self):
        assert self.user_access_control.access_level_for_object(self.dashboard) == "editor"
        assert self.other_user_access_control.access_level_for_object(self.dashboard) == "editor"


@pytest.mark.ee
class TestUserAccessControlFileSystem(BaseUserAccessControlTest):
    def setUp(self):
        super().setUp()

        # Enable advanced permissions & role-based access for tests
        self.organization.available_product_features = [
            {"key": "advanced_permissions", "name": "advanced_permissions"},
            {"key": "role_based_access", "name": "sso_enforcement"},
        ]
        self.organization.save()

        # We create a user that belongs to self.organization with membership
        # and a separate user that also belongs to the same org
        self.user_access_control = UserAccessControl(self.user, self.team)

        # Create some FileSystem rows
        # "my_resource" is the AccessControl resource
        # "abc"/"def" are the resource_id fields
        self.file_a = FileSystem.objects.create(
            team=self.team,
            path="top/folderA",
            depth=2,
            type="my_resource",
            ref="abc",
            created_by=self.user,
        )
        self.file_b = FileSystem.objects.create(
            team=self.team,
            path="top/folderB",
            depth=2,
            type="my_resource",
            ref="def",
            created_by=self.other_user,
        )

    def test_filtering_no_access_controls_means_default_editor(self):
        """
        By default, if no relevant AccessControl rows exist for (type,ref),
        the user gets 'editor' access. So both files should appear for the user.
        """
        queryset = FileSystem.objects.all()

        filtered_for_user = self.user_access_control.filter_and_annotate_file_system_queryset(queryset)
        self.assertCountEqual([self.file_a, self.file_b], filtered_for_user)

        filtered_for_other = self.other_user_access_control.filter_and_annotate_file_system_queryset(queryset)
        self.assertCountEqual([self.file_a, self.file_b], filtered_for_other)

        # We can also check the .effective_access_level annotation:
        a_for_user = filtered_for_user.get(id=self.file_a.id)
        b_for_user = filtered_for_user.get(id=self.file_b.id)
        self.assertEqual(a_for_user.effective_access_level, "some")  # type: ignore
        self.assertEqual(b_for_user.effective_access_level, "some")  # type: ignore

    def test_none_access_on_resource_excludes_items_for_non_creator(self):
        """
        If an AccessControl row specifically sets "none" for a resource_id,
        the user shouldn't see that FileSystem object, unless they are the creator or admin/staff.
        """
        # Mark file_b as "none" for self.user
        AccessControl.objects.create(
            team=self.team,
            resource="my_resource",
            resource_id="def",
            access_level="none",
            organization_member=None,  # global "none"
        )

        queryset = FileSystem.objects.all()
        filtered_for_user = self.user_access_control.filter_and_annotate_file_system_queryset(queryset)

        # user is the creator of file_a => sees it
        # user is NOT the creator of file_b => 'none' access => excluded
        self.assertCountEqual([self.file_a], filtered_for_user)

        # Meanwhile, other_user is the *creator* of file_b => they still see it
        filtered_for_other = self.other_user_access_control.filter_and_annotate_file_system_queryset(queryset)
        self.assertCountEqual([self.file_a, self.file_b], filtered_for_other)

    def test_org_admin_sees_all_even_if_none(self):
        # Make "def" = none for everyone
        AccessControl.objects.create(
            team=self.team,
            resource="my_resource",
            resource_id="def",
            access_level="none",
        )

        # Promote self.user to org admin
        membership = OrganizationMembership.objects.get(organization=self.organization, user=self.user)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        queryset = FileSystem.objects.all()
        filtered_for_user = self.user_access_control.filter_and_annotate_file_system_queryset(queryset)
        # Because user is org admin => sees everything
        self.assertCountEqual([self.file_a, self.file_b], filtered_for_user)

    def test_setting_explicit_viewer_or_editor_access(self):
        """
        If we explicitly set "viewer" or "editor" in AccessControl, that should override the default.
        """
        # Set "def" => "viewer" for self.user
        self._create_access_control(resource_id="def", access_level="viewer", resource="my_resource")
        # self._create_access_control_file_system(resource_id="def", access_level="viewer")
        # Set "abc" => "none" globally
        self._create_access_control(resource_id="abc", access_level="none", resource="my_resource")

        queryset = FileSystem.objects.all()
        filtered_for_user = self.user_access_control.filter_and_annotate_file_system_queryset(queryset)

        # file_a => "abc" => default is "none" from that row, but user is also the creator of file_a => sees it anyway
        # file_b => "def" => explicit "viewer" => user sees it
        self.assertCountEqual([self.file_a, self.file_b], filtered_for_user)

        # Meanwhile, other_user is the creator of file_b, but for file_a there's a "none" row
        # and other_user is not the creator of file_a => "none" excludes them from file_a
        filtered_for_other = self.other_user_access_control.filter_and_annotate_file_system_queryset(queryset)
        self.assertCountEqual([self.file_b], filtered_for_other)

    def test_project_admin_allows_visibility_even_if_none(self):
        """
        If the user is an 'admin' at the project level, they can see items even if there's
        a 'none' row for the resource in that project.
        """
        # 1) Mark file_b with "none" for everyone (global none).
        AccessControl.objects.create(
            team=self.team,
            resource="my_resource",
            resource_id="def",
            access_level="none",
        )

        # 2) Give self.user "admin" at the project level.
        #    This means resource='project', resource_id = team.id (string-cast if needed).
        self._create_access_control(
            resource="project",
            resource_id=str(self.team.id),  # important if resource_id is stored as string
            access_level="admin",
            organization_member=None,  # global rule (no specific org member), or you can tie to the user
            team=self.team,
        )

        queryset = FileSystem.objects.all()
        # Now, because user is project admin, they should see file_b despite 'none'
        filtered_for_user = self.user_access_control.filter_and_annotate_file_system_queryset(queryset)
        self.assertCountEqual([self.file_a, self.file_b], filtered_for_user)

        # 3) Remove the "admin" row, confirm user no longer sees file_b.
        AccessControl.objects.filter(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="admin",
        ).delete()
        self._clear_uac_caches()

        queryset = FileSystem.objects.all()
        filtered_for_user_after_removal = self.user_access_control.filter_and_annotate_file_system_queryset(queryset)
        # Now user is no longer project admin, so file_b is excluded again (they're not the creator).
        self.assertCountEqual([self.file_a], filtered_for_user_after_removal)


@pytest.mark.ee
class TestUserAccessControlSerializer(BaseUserAccessControlTest):
    def setUp(self):
        super().setUp()
        # We'll use Dashboard as a sample resource object
        from posthog.models.dashboard import Dashboard

        self.dashboard = Dashboard.objects.create(team=self.team)

        # Minimal serializer using the mixin
        class DummySerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
            class Meta:
                model = Dashboard
                fields = ("id", "user_access_level")

        self.Serializer = DummySerializer

    def test_object_level_access_when_no_resource_level(self):
        # No resource-level access controls, only object-level
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="viewer")
        serializer = self.Serializer(self.dashboard, context={"user_access_control": self.user_access_control})
        assert serializer.get_user_access_level(self.dashboard) == "viewer"

    def test_resource_level_takes_priority(self):
        # Both resource-level and object-level; resource-level should take priority
        self._create_access_control(resource="dashboard", resource_id=None, access_level="editor")
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="viewer")
        serializer = self.Serializer(self.dashboard, context={"user_access_control": self.user_access_control})
        assert serializer.get_user_access_level(self.dashboard) == "editor"

    def test_falls_back_to_object_level(self):
        # Only object-level present
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="editor")
        serializer = self.Serializer(self.dashboard, context={"user_access_control": self.user_access_control})
        assert serializer.get_user_access_level(self.dashboard) == "editor"

    def test_none_if_no_access(self):
        # No access controls at all
        serializer = self.Serializer(self.dashboard, context={"user_access_control": self.user_access_control})
        assert serializer.get_user_access_level(self.dashboard) == "editor"  # falls to default_access_level


# class TestUserDashboardPermissions(BaseTest, WithPermissionsBase):
#     def setUp(self):
#         super().setUp()
#         self.organization.available_product_features = [
#             {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
#         ]
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
#         self.organization.available_product_features = []
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
#         self.organization.available_product_features = [
#             {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
#         ]
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
#         self.organization.available_product_features = []
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
#         self.organization.available_product_features = [
#             {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
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

#             organization.available_product_features = [
#                 {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
#             ]
#             organization.save()

#             models.append((organization, membership, team))

#         user_permissions = UserPermissions(user)
#         with self.assertNumQueries(3):
#             assert len(user_permissions.team_ids_visible_for_user) == 10

#             for _, _, team in models:
#                 assert user_permissions.team(team).effective_membership_level == OrganizationMembership.Level.ADMIN
