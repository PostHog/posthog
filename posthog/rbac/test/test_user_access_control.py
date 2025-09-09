import pytest
from posthog.test.base import BaseTest

from rest_framework import serializers

from posthog.constants import AvailableFeature
from posthog.models.dashboard import Dashboard
from posthog.models.file_system.file_system import FileSystem
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import (
    RESOURCE_INHERITANCE_MAP,
    AccessSource,
    UserAccessControl,
    UserAccessControlSerializerMixin,
    get_field_access_control_map,
)

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

        assert self.user_access_control.access_level_for_object(self.dashboard) == "manager"
        assert self.other_user_access_control.access_level_for_object(self.dashboard) == "editor"
        assert self.user_access_control.access_level_for_resource("dashboard") == "manager"
        assert self.other_user_access_control.access_level_for_resource("dashboard") == "editor"

    def test_ac_object_default_response(self):
        assert self.user_access_control.access_level_for_object(self.dashboard) == "editor"
        assert self.other_user_access_control.access_level_for_object(self.dashboard) == "editor"

    def test_setting_explicit_manager_access(self):
        """
        Test that the new 'manager' access level works correctly and is above 'editor' in the hierarchy.
        """
        # Test that creators have "manager" access to their files by default:
        # - User is creator of dashboard -> has "manager" access
        # Create an AccessControl entry giving other_user "editor" access to the dashboard
        # to verify they can edit but not manage it

        self._create_access_control(
            resource_id=self.dashboard.id,
            access_level="editor",
            resource="dashboard",
            organization_member=self.other_user.organization_memberships.first(),
        )

        assert self.other_user_access_control.check_access_level_for_object(self.dashboard, "editor") is True
        assert self.other_user_access_control.check_access_level_for_object(self.dashboard, "manager") is False


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

    def test_manager_access_level_serializer(self):
        # Test that the new 'manager' level works in serializers
        self._create_access_control(resource="dashboard", resource_id=str(self.dashboard.id), access_level="manager")
        serializer = self.Serializer(self.dashboard, context={"user_access_control": self.user_access_control})
        assert serializer.get_user_access_level(self.dashboard) == "manager"


class TestUserAccessControlAccessSource(BaseUserAccessControlTest):
    """Test the get_access_source_for_object method"""

    def setUp(self):
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)

    def test_creator_access_source(self):
        """Test that creator gets 'creator' access source"""
        access_source = self.user_access_control.get_access_source_for_object(self.dashboard)
        assert access_source == AccessSource.CREATOR

    def test_organization_admin_access_source(self):
        """Test that org admins get 'organization_admin' access source"""
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create a dashboard by another user
        other_dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

        access_source = self.user_access_control.get_access_source_for_object(other_dashboard)
        assert access_source == AccessSource.ORGANIZATION_ADMIN

    def test_explicit_member_access_source(self):
        """Test that explicit member access gets 'explicit_member' access source"""
        # Create a dashboard by another user
        other_dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

        # Give explicit access to the current user
        self._create_access_control(
            resource="dashboard",
            resource_id=str(other_dashboard.id),
            access_level="viewer",
            organization_member=self.organization_membership,
        )

        # Create a fresh UserAccessControl instance to pick up the new access control
        fresh_user_access_control = UserAccessControl(self.user, self.team)

        access_source = fresh_user_access_control.get_access_source_for_object(other_dashboard)
        assert access_source == AccessSource.EXPLICIT_MEMBER

    def test_explicit_role_access_source(self):
        """Test that explicit role access gets 'explicit_role' access source"""
        # Create a dashboard by another user
        other_dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

        # Give role access
        self._create_access_control(
            resource="dashboard", resource_id=str(other_dashboard.id), access_level="viewer", role=self.role_a
        )

        # Create a fresh UserAccessControl instance to pick up the new access control
        fresh_user_access_control = UserAccessControl(self.user, self.team)

        access_source = fresh_user_access_control.get_access_source_for_object(other_dashboard)
        assert access_source == AccessSource.EXPLICIT_ROLE

    def test_project_admin_access_source(self):
        """Test that project-level access gets 'project_admin' access source"""
        # Create a dashboard by another user
        other_dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

        # Give project-level access to the current user
        self._create_access_control(
            resource="project",
            resource_id=str(self.team.id),
            access_level="admin",
            organization_member=self.organization_membership,
        )

        # Create a fresh UserAccessControl instance to pick up the new access control
        fresh_user_access_control = UserAccessControl(self.user, self.team)

        access_source = fresh_user_access_control.get_access_source_for_object(other_dashboard)
        assert access_source == AccessSource.PROJECT_ADMIN

    def test_default_access_source(self):
        """Test that default access gets 'default' access source"""
        # Create a dashboard by another user
        other_dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

        access_source = self.user_access_control.get_access_source_for_object(other_dashboard)
        assert access_source == AccessSource.DEFAULT

    def test_access_source_prioritization(self):
        """Test that access sources are prioritized correctly"""
        # Create a dashboard by another user
        other_dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

        # Give explicit member access
        self._create_access_control(
            resource="dashboard",
            resource_id=str(other_dashboard.id),
            access_level="viewer",
            organization_member=self.organization_membership,
        )

        # Make user org admin (should override explicit access)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create a fresh UserAccessControl instance to pick up the new membership level
        fresh_user_access_control = UserAccessControl(self.user, self.team)

        access_source = fresh_user_access_control.get_access_source_for_object(other_dashboard)
        assert access_source == AccessSource.ORGANIZATION_ADMIN

    def test_access_source_without_access_controls_supported(self):
        """Test access source when access controls are not supported"""
        # Disable access controls
        self.organization.available_product_features = []
        self.organization.save()

        # Create a dashboard by another user
        other_dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

        access_source = self.user_access_control.get_access_source_for_object(other_dashboard)
        assert access_source == AccessSource.DEFAULT

    def test_access_source_returns_none_for_no_context(self):
        """Test that access source returns None when there's no access context"""
        # Create a user with no organization membership
        user_without_org = User.objects.create_user(
            email="noorg@example.com", password="password", first_name="No", last_name="Org"
        )
        uac = UserAccessControl(user=user_without_org, team=self.team)

        access_source = uac.get_access_source_for_object(self.dashboard)
        assert access_source is None

    def test_access_source_with_team_object(self):
        """Test access source for team objects"""
        access_source = self.user_access_control.get_access_source_for_object(self.team)
        assert access_source == AccessSource.DEFAULT  # Default for teams unless org admin

        # Make user org admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create a fresh UserAccessControl instance to pick up the new membership level
        fresh_user_access_control = UserAccessControl(self.user, self.team)

        access_source = fresh_user_access_control.get_access_source_for_object(self.team)
        assert access_source == AccessSource.ORGANIZATION_ADMIN


@pytest.mark.ee
class TestUserAccessControlGetUserAccessLevel(BaseUserAccessControlTest):
    """Test the get_user_access_level method"""

    def setUp(self):
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        self.other_dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

    def test_specific_access_level_for_object_takes_priority(self):
        """Test that specific access level (with role/member) takes highest priority"""
        # Create a specific access control for the user on other_dashboard
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.other_dashboard.id),
            access_level="viewer",
            organization_member=self.organization_membership,
        )

        # Create a resource-level access control that would give higher access
        self._create_access_control(
            resource="dashboard",
            resource_id=None,
            access_level="editor",
        )

        access_level = self.user_access_control.get_user_access_level(self.other_dashboard)
        assert access_level == "viewer"  # Specific object access takes priority

    def test_resource_level_access_when_no_specific_object_access(self):
        """Test that resource-level access is used when no specific object access exists"""
        # Create only resource-level access control
        self._create_access_control(
            resource="dashboard",
            resource_id=None,
            access_level="editor",
        )

        access_level = self.user_access_control.get_user_access_level(self.other_dashboard)
        assert access_level == "editor"

    def test_object_general_access_as_fallback(self):
        """Test that object general access is used as final fallback"""
        # No specific or resource-level access controls
        # Should fall back to object general access (creator gets highest level)
        access_level = self.user_access_control.get_user_access_level(self.dashboard)
        assert access_level == "manager"  # Creator gets highest access level

    def test_org_admin_gets_highest_access_level(self):
        """Test that org admins get highest access level regardless of other controls"""
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create restrictive access controls
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.other_dashboard.id),
            access_level="viewer",
            organization_member=self.organization_membership,
        )

        access_level = self.user_access_control.get_user_access_level(self.other_dashboard)
        assert access_level == "manager"  # Org admin gets highest level

    def test_creator_gets_highest_access_level(self):
        """Test that creators get highest access level for their objects"""
        access_level = self.user_access_control.get_user_access_level(self.dashboard)
        assert access_level == "manager"  # Creator gets highest level

    def test_no_access_controls_returns_default(self):
        """Test that when no access controls exist, default access level is returned"""
        # Disable access controls
        self.organization.available_product_features = []
        self.organization.save()

        access_level = self.user_access_control.get_user_access_level(self.other_dashboard)
        assert access_level == "editor"  # Default access level

    def test_role_based_specific_access(self):
        """Test that role-based specific access works correctly"""
        # Create role-based access control
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.other_dashboard.id),
            access_level="viewer",
            role=self.role_a,
        )

        access_level = self.user_access_control.get_user_access_level(self.other_dashboard)
        assert access_level == "viewer"

    def test_mixed_access_controls_highest_wins(self):
        """Test that when multiple access controls exist, highest level wins"""
        # Create multiple access controls with different levels
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.other_dashboard.id),
            access_level="viewer",
            organization_member=self.organization_membership,
        )
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.other_dashboard.id),
            access_level="editor",
            role=self.role_a,
        )

        access_level = self.user_access_control.get_user_access_level(self.other_dashboard)
        assert access_level == "editor"  # Higher level wins

    def test_project_level_access_for_team_objects(self):
        """Test project-level access for team objects"""
        # Create project-level access control
        self._create_access_control(
            resource="project",
            resource_id=str(self.team.id),
            access_level="admin",
            organization_member=self.organization_membership,
        )

        access_level = self.user_access_control.get_user_access_level(self.team)
        assert access_level == "admin"

    def test_organization_access_for_organization_objects_member(self):
        """Test organization access for organization objects"""
        uac = UserAccessControl(user=self.user, organization_id=self.organization.id)

        access_level = uac.get_user_access_level(self.organization)
        assert access_level == "member"  # Default for org members

    def test_organization_access_for_organization_objects_admin(self):
        """Test organization access for organization objects"""
        uac = UserAccessControl(user=self.user, organization_id=self.organization.id)

        # Make user org admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        access_level = uac.get_user_access_level(self.organization)
        assert access_level == "admin"

    def test_no_organization_membership_returns_none(self):
        """Test that users without org membership get None access level"""
        # Create user without org membership
        user_without_org = User.objects.create_user(
            email="noorg@example.com", password="password", first_name="No", last_name="Org"
        )
        uac = UserAccessControl(user=user_without_org, team=self.team)

        access_level = uac.get_user_access_level(self.dashboard)
        assert access_level is None

    def test_unsupported_model_returns_none(self):
        """Test that unsupported models return None"""

        # Create a model that doesn't map to a resource
        class UnsupportedModel:
            def __init__(self):
                self.id = 1

        unsupported_obj = UnsupportedModel()
        access_level = self.user_access_control.get_user_access_level(unsupported_obj)  # type: ignore
        assert access_level is None


@pytest.mark.ee
class TestUserAccessControlSpecificAccessLevelForObject(BaseUserAccessControlTest):
    """Test the specific_access_level_for_object method"""

    def setUp(self):
        super().setUp()
        self.dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        self.other_dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)

    def test_returns_none_when_no_specific_access_controls(self):
        """Test that returns None when no specific access controls exist"""
        access_level = self.other_user_access_control.specific_access_level_for_object(self.dashboard)
        assert access_level is None

    def test_returns_none_when_no_organization_membership(self):
        """Test that returns None when user has no organization membership"""
        # Create user without org membership
        user_without_org = User.objects.create_user(
            email="noorg@example.com", password="password", first_name="No", last_name="Org"
        )
        uac = UserAccessControl(user=user_without_org, team=self.team)

        access_level = uac.specific_access_level_for_object(self.dashboard)
        assert access_level is None

    def test_returns_none_for_unsupported_model(self):
        """Test that returns None for unsupported models"""

        class UnsupportedModel:
            def __init__(self):
                self.id = 1

        unsupported_obj = UnsupportedModel()
        access_level = self.user_access_control.specific_access_level_for_object(unsupported_obj)  # type: ignore
        assert access_level is None

    def test_member_specific_access_control(self):
        """Test that member-specific access controls are detected"""
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.other_dashboard.id),
            access_level="viewer",
            organization_member=self.organization_membership,
        )

        access_level = self.user_access_control.specific_access_level_for_object(self.other_dashboard)
        assert access_level == "viewer"

    def test_role_specific_access_control(self):
        """Test that role-specific access controls are detected"""
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.other_dashboard.id),
            access_level="editor",
            role=self.role_a,
        )

        access_level = self.user_access_control.specific_access_level_for_object(self.other_dashboard)
        assert access_level == "editor"

    def test_ignores_resource_level_access_controls(self):
        """Test that resource level access controls (no member/role) are ignored"""
        # Create a resource level access control
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.other_dashboard.id),
            access_level="manager",
        )

        access_level = self.user_access_control.specific_access_level_for_object(self.other_dashboard)
        assert access_level is None  # Global controls are ignored

    def test_highest_level_wins_for_multiple_specific_controls(self):
        """Test that highest level wins when multiple specific controls exist"""
        # Create multiple specific access controls
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.other_dashboard.id),
            access_level="viewer",
            organization_member=self.organization_membership,
        )
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.other_dashboard.id),
            access_level="editor",
            role=self.role_a,
        )

        access_level = self.user_access_control.specific_access_level_for_object(self.other_dashboard)
        assert access_level == "editor"  # Higher level wins

    def test_mixed_member_and_role_controls(self):
        """Test that both member and role controls are considered"""
        # Create member-specific control
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.other_dashboard.id),
            access_level="viewer",
            organization_member=self.organization_membership,
        )
        # Create role-specific control with higher level
        self._create_access_control(
            resource="dashboard",
            resource_id=str(self.other_dashboard.id),
            access_level="manager",
            role=self.role_a,
        )

        access_level = self.user_access_control.specific_access_level_for_object(self.other_dashboard)
        assert access_level == "manager"  # Role control with higher level wins

    def test_project_specific_access_control(self):
        """Test project-specific access controls"""
        self._create_access_control(
            resource="project",
            resource_id=str(self.team.id),
            access_level="admin",
            organization_member=self.organization_membership,
        )

        access_level = self.user_access_control.specific_access_level_for_object(self.team)
        assert access_level == "admin"

    def test_organization_specific_access_control(self):
        """Test organization-specific access controls"""
        uac = UserAccessControl(user=self.user, organization_id=self.organization.id)

        access_level = uac.specific_access_level_for_object(self.organization)
        assert access_level == "member"

    def test_feature_flag_specific_access_control(self):
        """Test feature flag-specific access controls"""
        from posthog.models.feature_flag import FeatureFlag

        feature_flag = FeatureFlag.objects.create(team=self.team, created_by=self.other_user)

        self._create_access_control(
            resource="feature_flag",
            resource_id=str(feature_flag.id),
            access_level="viewer",
            organization_member=self.organization_membership,
        )

        access_level = self.user_access_control.specific_access_level_for_object(feature_flag)
        assert access_level == "viewer"

    def test_notebook_specific_access_control(self):
        """Test notebook-specific access controls"""
        from posthog.models.notebook import Notebook

        notebook = Notebook.objects.create(team=self.team, created_by=self.other_user)

        self._create_access_control(
            resource="notebook",
            resource_id=str(notebook.id),
            access_level="editor",
            role=self.role_a,
        )

        access_level = self.user_access_control.specific_access_level_for_object(notebook)
        assert access_level == "editor"

    def test_insight_specific_access_control(self):
        """Test insight-specific access controls"""
        from posthog.models.insight import Insight

        insight = Insight.objects.create(team=self.team, created_by=self.other_user)

        self._create_access_control(
            resource="insight",
            resource_id=str(insight.id),
            access_level="viewer",
            organization_member=self.organization_membership,
        )

        access_level = self.user_access_control.specific_access_level_for_object(insight)
        assert access_level == "viewer"


@pytest.mark.ee
class TestSpecificObjectAccessControl(BaseUserAccessControlTest):
    """
    Test the new functionality for specific object access when user has "none" resource access.
    This covers the use case where a user has no general access to a resource type but
    has been granted access to specific objects within that resource type.
    """

    def setUp(self):
        super().setUp()
        # Create test notebooks for various scenarios
        from posthog.models.notebook.notebook import Notebook

        self.notebook_1 = Notebook.objects.create(team=self.team, created_by=self.other_user, title="Notebook 1")
        self.notebook_2 = Notebook.objects.create(team=self.team, created_by=self.other_user, title="Notebook 2")
        self.notebook_3 = Notebook.objects.create(team=self.team, created_by=self.user, title="My Notebook")

    def test_has_any_specific_access_for_resource_with_specific_access(self):
        """Test has_any_specific_access_for_resource returns True when user has specific object access"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        # Give specific access to notebook_1
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_1.id),
            access_level="editor",
            organization_member=self.organization_membership,
        )

        self._clear_uac_caches()

        # Should return True because user has specific access to at least one notebook
        assert self.user_access_control.has_any_specific_access_for_resource("notebook", "editor") is True
        assert self.user_access_control.has_any_specific_access_for_resource("notebook", "viewer") is True

    def test_has_any_specific_access_for_resource_without_specific_access(self):
        """Test has_any_specific_access_for_resource returns False when user has no specific access"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        self._clear_uac_caches()

        # Should return False because user has no specific object access
        assert self.user_access_control.has_any_specific_access_for_resource("notebook", "editor") is False
        assert self.user_access_control.has_any_specific_access_for_resource("notebook", "viewer") is False

    def test_effective_access_level_for_resource_with_resource_access(self):
        """Test effective_access_level_for_resource returns resource level when user has resource access"""
        # Set resource-level access to "editor"
        self._create_access_control(resource="notebook", access_level="editor")

        self._clear_uac_caches()

        # Should return the resource-level access
        assert self.user_access_control.effective_access_level_for_resource("notebook") == "editor"

    def test_effective_access_level_for_resource_with_none_resource_and_specific_access(self):
        """Test effective_access_level_for_resource returns 'viewer' when user has 'none' resource but specific access"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        # Give specific access to notebook_1
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_1.id),
            access_level="editor",
            organization_member=self.organization_membership,
        )

        self._clear_uac_caches()

        # Should return "viewer" to allow navigation but not creation
        assert self.user_access_control.effective_access_level_for_resource("notebook") == "viewer"

    def test_effective_access_level_for_resource_with_none_resource_and_no_specific_access(self):
        """Test effective_access_level_for_resource returns 'none' when user has no access"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        self._clear_uac_caches()

        # Should return "none" because user has no access at all
        assert self.user_access_control.effective_access_level_for_resource("notebook") == "none"

    def test_filter_queryset_by_access_level_with_none_resource_and_specific_access(self):
        """Test queryset filtering when user has 'none' resource access but specific object access"""
        from posthog.models.notebook.notebook import Notebook

        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        # Give specific access to notebook_1 only
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_1.id),
            access_level="editor",
            organization_member=self.organization_membership,
        )

        self._clear_uac_caches()

        # Filter the queryset
        queryset = Notebook.objects.all()
        filtered_queryset = self.user_access_control.filter_queryset_by_access_level(queryset)

        # Should only include notebook_1 (specific access) and notebook_3 (created by user)
        notebook_ids = list(filtered_queryset.values_list("id", flat=True))
        assert self.notebook_1.id in notebook_ids
        assert self.notebook_3.id in notebook_ids  # Created by user
        assert self.notebook_2.id not in notebook_ids  # No access

    def test_filter_queryset_by_access_level_with_resource_access(self):
        """Test queryset filtering when user has resource-level access"""
        from posthog.models.notebook.notebook import Notebook

        # Set resource-level access to "editor"
        self._create_access_control(resource="notebook", access_level="editor")

        # Block specific access to notebook_2
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_2.id),
            access_level="none",
            organization_member=self.organization_membership,
        )

        self._clear_uac_caches()

        # Filter the queryset
        queryset = Notebook.objects.all()
        filtered_queryset = self.user_access_control.filter_queryset_by_access_level(queryset)

        # Should include notebook_1 and notebook_3, but exclude notebook_2
        notebook_ids = list(filtered_queryset.values_list("id", flat=True))
        assert self.notebook_1.id in notebook_ids
        assert self.notebook_3.id in notebook_ids
        assert self.notebook_2.id not in notebook_ids  # Explicitly blocked

    def test_get_user_access_level_with_specific_access_priority(self):
        """Test that get_user_access_level prioritizes specific access over resource access"""
        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        # Give specific access to notebook_1
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_1.id),
            access_level="editor",
            organization_member=self.organization_membership,
        )

        self._clear_uac_caches()

        # Should return specific access level for notebook_1
        assert self.user_access_control.get_user_access_level(self.notebook_1) == "editor"

        # Should return None for notebook_2 (no specific access and "none" resource access)
        assert self.user_access_control.get_user_access_level(self.notebook_2) == "none"

    def test_user_access_control_serializer_mixin_with_specific_access(self):
        """Test UserAccessControlSerializerMixin returns correct access levels"""
        from rest_framework import serializers

        from posthog.models.notebook.notebook import Notebook

        # Set resource-level access to "none"
        self._create_access_control(resource="notebook", access_level="none")

        # Give specific access to notebook_1
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_1.id),
            access_level="editor",
            organization_member=self.organization_membership,
        )

        self._clear_uac_caches()

        class NotebookSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
            class Meta:
                model = Notebook
                fields = ("id", "title", "user_access_level")

        # Test serialization with user_access_control in context
        serializer = NotebookSerializer(
            [self.notebook_1, self.notebook_2], many=True, context={"user_access_control": self.user_access_control}
        )

        data = serializer.data

        # notebook_1 should have "editor" access
        notebook_1_data = next(item for item in data if item["id"] == str(self.notebook_1.id))
        assert notebook_1_data["user_access_level"] == "editor"

        # notebook_2 should have "none" access
        notebook_2_data = next(item for item in data if item["id"] == str(self.notebook_2.id))
        assert notebook_2_data["user_access_level"] == "none"


@pytest.mark.ee
class TestEffectiveAccessLevelForResource(BaseUserAccessControlTest):
    """Test the effective_access_level_for_resource method"""

    def test_returns_resource_level_when_user_has_resource_access(self):
        """Test that resource-level access is returned when user has it"""
        self._create_access_control(resource="dashboard", access_level="editor")
        self._clear_uac_caches()

        assert self.user_access_control.effective_access_level_for_resource("dashboard") == "editor"

    def test_returns_viewer_when_none_resource_but_has_specific_access(self):
        """Test that 'viewer' is returned when user has 'none' resource access but specific object access"""
        # Set resource-level access to "none"
        self._create_access_control(resource="dashboard", access_level="none")

        # Create a dashboard and give specific access
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)
        self._create_access_control(
            resource="dashboard",
            resource_id=str(dashboard.id),
            access_level="editor",
            organization_member=self.organization_membership,
        )

        self._clear_uac_caches()

        # Should return "viewer" to allow navigation but not creation
        assert self.user_access_control.effective_access_level_for_resource("dashboard") == "viewer"

    def test_returns_none_when_no_access_at_all(self):
        """Test that 'none' is returned when user has no access"""
        self._create_access_control(resource="dashboard", access_level="none")
        self._clear_uac_caches()

        assert self.user_access_control.effective_access_level_for_resource("dashboard") == "none"

    def test_role_based_resource_access(self):
        """Test that role-based resource access works correctly"""
        self._create_access_control(resource="dashboard", access_level="editor", role=self.role_a)
        self._clear_uac_caches()

        assert self.user_access_control.effective_access_level_for_resource("dashboard") == "editor"

    def test_mixed_access_controls_highest_wins(self):
        """Test that when multiple access controls exist, highest level wins"""
        # Create multiple access controls with different levels
        self._create_access_control(resource="dashboard", access_level="viewer")
        self._create_access_control(resource="dashboard", access_level="editor", role=self.role_a)
        self._clear_uac_caches()

        assert self.user_access_control.effective_access_level_for_resource("dashboard") == "editor"

    def test_org_admin_gets_highest_access_level(self):
        """Test that org admins get highest access level regardless of other controls"""
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create restrictive access controls
        self._create_access_control(resource="dashboard", access_level="viewer")
        self._clear_uac_caches()

        assert self.user_access_control.effective_access_level_for_resource("dashboard") == "manager"

    def test_without_available_product_features_returns_default(self):
        """Test that default access is returned when RBAC features are not available"""
        self.organization.available_product_features = []
        self.organization.save()

        # Make user org admin to test admin path
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        assert self.user_access_control.effective_access_level_for_resource("dashboard") == "manager"

        # Test non-admin path
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        fresh_user_access_control = UserAccessControl(self.user, self.team)
        assert fresh_user_access_control.effective_access_level_for_resource("dashboard") == "editor"

    def test_user_without_organization_membership_returns_none(self):
        """Test that users without org membership get None"""
        user_without_org = User.objects.create_user(
            email="noorg@example.com", password="password", first_name="No", last_name="Org"
        )
        uac = UserAccessControl(user=user_without_org, team=self.team)

        assert uac.effective_access_level_for_resource("dashboard") is None

    def test_different_resource_types(self):
        """Test effective access level for different resource types"""
        # Test project resource
        self._create_access_control(resource="project", access_level="admin")
        self._clear_uac_caches()
        assert self.user_access_control.effective_access_level_for_resource("project") == "admin"

        # Test notebook resource
        self._create_access_control(resource="notebook", access_level="editor")
        self._clear_uac_caches()
        assert self.user_access_control.effective_access_level_for_resource("notebook") == "editor"

        # Test feature_flag resource
        self._create_access_control(resource="feature_flag", access_level="viewer")
        self._clear_uac_caches()
        assert self.user_access_control.effective_access_level_for_resource("feature_flag") == "viewer"

    def test_multiple_specific_access_different_levels(self):
        """Test effective access when user has multiple specific access controls with different levels"""
        # Set resource-level access to "none"
        self._create_access_control(resource="dashboard", access_level="none")

        # Create dashboards with different access levels
        dashboard1 = Dashboard.objects.create(team=self.team, created_by=self.other_user)
        dashboard2 = Dashboard.objects.create(team=self.team, created_by=self.other_user)

        self._create_access_control(
            resource="dashboard",
            resource_id=str(dashboard1.id),
            access_level="viewer",
            organization_member=self.organization_membership,
        )
        self._create_access_control(
            resource="dashboard",
            resource_id=str(dashboard2.id),
            access_level="editor",
            role=self.role_a,
        )

        self._clear_uac_caches()

        # Should return "viewer" (navigation level) regardless of specific access levels
        assert self.user_access_control.effective_access_level_for_resource("dashboard") == "viewer"


@pytest.mark.ee
class TestResourceInheritance(BaseUserAccessControlTest):
    def test_session_recording_playlist_inherits_from_session_recording(self):
        """Test that session_recording_playlist inherits access from session_recording"""
        # Verify the inheritance mapping exists
        assert "session_recording_playlist" in RESOURCE_INHERITANCE_MAP
        assert RESOURCE_INHERITANCE_MAP["session_recording_playlist"] == "session_recording"

        # Give the user viewer access to session recordings
        self._create_access_control(
            resource="session_recording",
            resource_id=None,
            access_level="viewer",
            organization_member=self.organization_membership,
        )
        self._clear_uac_caches()

        # Check that the user has viewer access to session_recording_playlist through inheritance
        assert self.user_access_control.access_level_for_resource("session_recording_playlist") == "viewer"
        assert self.user_access_control.check_access_level_for_resource("session_recording_playlist", "viewer") is True
        assert self.user_access_control.check_access_level_for_resource("session_recording_playlist", "editor") is False

    def test_inherited_resource_respects_parent_access_levels(self):
        """Test that inherited resources use parent's access levels for comparison"""
        # Give the user editor access to session recordings
        self._create_access_control(
            resource="session_recording",
            resource_id=None,
            access_level="editor",
            organization_member=self.organization_membership,
        )
        self._clear_uac_caches()

        # Check that the user has editor access to session_recording_playlist
        assert self.user_access_control.access_level_for_resource("session_recording_playlist") == "editor"
        assert self.user_access_control.check_access_level_for_resource("session_recording_playlist", "viewer") is True
        assert self.user_access_control.check_access_level_for_resource("session_recording_playlist", "editor") is True
        assert (
            self.user_access_control.check_access_level_for_resource("session_recording_playlist", "manager") is False
        )

    def test_org_admin_has_full_access_to_inherited_resources(self):
        """Test that org admins have full access to inherited resources"""
        # Make user an org admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self._clear_uac_caches()

        # Check that org admin has highest level access to session_recording_playlist
        assert self.user_access_control.access_level_for_resource("session_recording_playlist") == "manager"
        assert self.user_access_control.check_access_level_for_resource("session_recording_playlist", "manager") is True

    def test_no_access_to_parent_means_no_access_to_inherited(self):
        """Test that no access to parent resource means no access to inherited resource"""
        # Give the user no access to session recordings
        self._create_access_control(
            resource="session_recording",
            resource_id=None,
            access_level="none",
            organization_member=self.organization_membership,
        )
        self._clear_uac_caches()

        # Check that the user has no access to session_recording_playlist
        assert self.user_access_control.access_level_for_resource("session_recording_playlist") == "none"
        assert self.user_access_control.check_access_level_for_resource("session_recording_playlist", "viewer") is False


@pytest.mark.ee
class TestFieldLevelAccessControl(BaseUserAccessControlTest):
    def test_field_access_control_mapping_exists(self):
        """Test that field access control mappings are properly configured"""
        team_mappings = get_field_access_control_map(Team)

        # Verify session recording fields are mapped
        assert "session_recording_opt_in" in team_mappings
        assert team_mappings["session_recording_opt_in"] == ("session_recording", "editor")
        assert "session_recording_sample_rate" in team_mappings
        assert team_mappings["session_recording_sample_rate"] == ("session_recording", "editor")

    def test_field_validation_blocks_without_access(self):
        """Test that field validation blocks updates without proper access"""
        from rest_framework.exceptions import ValidationError

        # Give user only viewer access to session recordings
        self._create_access_control(
            resource="session_recording",
            resource_id=None,
            access_level="viewer",
            organization_member=self.organization_membership,
        )
        self._clear_uac_caches()

        # Create a mock serializer with access control mixin
        class TeamSerializer(UserAccessControlSerializerMixin):
            pass

        # Create serializer with team instance
        view_mock = type("view", (), {"user_access_control": self.user_access_control})()
        serializer = TeamSerializer(instance=self.team, context={"view": view_mock})

        # Try to modify a protected field - should raise validation error
        attrs = {"session_recording_opt_in": True}
        with pytest.raises(ValidationError) as exc_info:
            serializer.validate(attrs)

        detail = exc_info.value.detail
        assert isinstance(detail, dict), f"Expected dict but got {type(detail)}"
        assert "session_recording_opt_in" in detail
        # The error is a list, get the actual message
        error_detail = detail["session_recording_opt_in"]
        error_msg = str(error_detail[0]) if isinstance(error_detail, list) else str(error_detail)
        assert "editor access to session recordings" in error_msg, f"Got error message: {error_msg!r}"

    def test_field_validation_allows_with_proper_access(self):
        """Test that field validation allows updates with proper access"""
        # Give user editor access to session recordings
        self._create_access_control(
            resource="session_recording",
            resource_id=None,
            access_level="editor",
            organization_member=self.organization_membership,
        )
        self._clear_uac_caches()

        # Create a mock serializer with access control mixin
        class TeamSerializer(UserAccessControlSerializerMixin):
            pass

        # Create serializer with team instance
        view_mock = type("view", (), {"user_access_control": self.user_access_control})()
        serializer = TeamSerializer(instance=self.team, context={"view": view_mock})

        # Try to modify a protected field - should succeed
        attrs = {"session_recording_opt_in": True}
        result = serializer.validate(attrs)
        assert result == attrs

    def test_field_validation_skipped_for_creates(self):
        """Test that field validation is skipped for creates (only applies to updates)"""
        # Don't give user any access
        self._clear_uac_caches()

        # Create a mock serializer with access control mixin
        class TeamSerializer(UserAccessControlSerializerMixin):
            pass

        # Create serializer without instance (simulating create)
        view_mock = type("view", (), {"user_access_control": self.user_access_control})()
        serializer = TeamSerializer(instance=None, context={"view": view_mock})

        # Try to set a protected field during create - should succeed
        attrs = {"session_recording_opt_in": True}
        result = serializer.validate(attrs)
        assert result == attrs

    def test_field_validation_allows_non_protected_fields(self):
        """Test that field validation allows updates to non-protected fields"""
        # Don't give user any session recording access
        self._clear_uac_caches()

        # Create a mock serializer with access control mixin
        class TeamSerializer(UserAccessControlSerializerMixin):
            pass

        # Create serializer with team instance
        view_mock = type("view", (), {"user_access_control": self.user_access_control})()
        serializer = TeamSerializer(instance=self.team, context={"view": view_mock})

        # Try to modify a non-protected field - should succeed
        attrs = {"name": "New Team Name"}
        result = serializer.validate(attrs)
        assert result == attrs

    def test_field_validation_with_org_admin(self):
        """Test that org admins can modify protected fields"""
        # Make user an org admin
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self._clear_uac_caches()

        # Create a mock serializer with access control mixin
        class TeamSerializer(UserAccessControlSerializerMixin):
            pass

        # Create serializer with team instance
        view_mock = type("view", (), {"user_access_control": self.user_access_control})()
        serializer = TeamSerializer(instance=self.team, context={"view": view_mock})

        # Try to modify protected fields - should succeed for org admin
        attrs = {"session_recording_opt_in": True, "session_recording_sample_rate": 0.5}
        result = serializer.validate(attrs)
        assert result == attrs
