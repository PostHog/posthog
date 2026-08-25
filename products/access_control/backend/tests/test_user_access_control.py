import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import serializers

from posthog.constants import AvailableFeature
from posthog.models.file_system.file_system import FileSystem
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.subject_access_control import SubjectAccessControl
from products.access_control.backend.facade.user_access_control import (
    RESOURCE_INHERITANCE_MAP,
    AccessSource,
    UserAccessControl,
    get_field_access_control_map,
    model_to_resource,
)
from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.access_control.backend.presentation.access_control import UserAccessControlSerializerMixin
from products.dashboards.backend.models.dashboard import Dashboard
from products.replay_vision.backend.models.vision_action import VisionAction, VisionActionRun
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource


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
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
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
    def test_vision_action_models_map_to_vision_action_resource(self):
        # VisionAction/VisionActionRun's _meta.model_name (visionaction/visionactionrun) differs from the
        # vision_action scope object, so without the explicit mapping they silently drop out of
        # object-level access control and a per-action grant wouldn't be enforced.
        assert model_to_resource(VisionAction()) == "vision_action"
        assert model_to_resource(VisionActionRun()) == "vision_action"

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

    @parameterized.expand(
        [
            ("denial", "none", "member", "member"),
            ("grant", "admin", "none", "none"),
        ]
    )
    def test_role_rule_from_another_organization_is_ignored(self, _name, role_level, default_level, expected_level):
        # Nothing scopes the role on an AccessControl row to the project's organization, so a rule
        # can name a role the user holds in an unrelated organization
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self._create_access_control(resource_id=str(self.team.id), access_level=default_level)

        other_organization = Organization.objects.create(name="Other organization")
        other_membership = OrganizationMembership.objects.create(
            organization=other_organization, user=self.user, level=OrganizationMembership.Level.MEMBER
        )
        foreign_role = Role.objects.create(name="Foreign role", organization=other_organization)
        RoleMembership.objects.create(role=foreign_role, user=self.user, organization_member=other_membership)
        self._create_access_control(resource_id=str(self.team.id), access_level=role_level, role=foreign_role)

        self._clear_uac_caches()
        assert self.user_access_control._user_role_ids == [self.role_a.id]
        assert self.user_access_control.get_user_access_level(self.team) == expected_level

    @parameterized.expand(
        [
            ("denial", "none", "member", "member"),
            ("grant", "admin", "none", "none"),
        ]
    )
    def test_member_rule_from_another_organization_is_ignored(self, _name, member_level, default_level, expected_level):
        # Same as above for the member arm: nothing scopes `organization_member` to the project's
        # organization, so a rule can name a membership the user holds in an unrelated organization
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self._create_access_control(resource_id=str(self.team.id), access_level=default_level)

        other_organization = Organization.objects.create(name="Other organization")
        other_membership = OrganizationMembership.objects.create(
            organization=other_organization, user=self.user, level=OrganizationMembership.Level.MEMBER
        )
        self._create_access_control(
            resource_id=str(self.team.id), access_level=member_level, organization_member=other_membership
        )

        self._clear_uac_caches()
        assert self.user_access_control.get_user_access_level(self.team) == expected_level

    def test_without_available_product_features(self):
        self.organization.available_product_features = []
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        assert self.user_access_control.access_level_for_object(self.team) == "admin"
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is True
        assert self.other_user_access_control.access_level_for_object(self.team) == "admin"
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is True
        resource_access = self.user_access_control.access_level_for_resource("project")
        assert resource_access and resource_access.access_level == "admin"
        resource_access = self.other_user_access_control.access_level_for_resource("project")
        assert resource_access and resource_access.access_level == "admin"
        assert self.user_access_control.check_can_modify_access_levels_for_object(self.team) is True
        assert self.other_user_access_control.check_can_modify_access_levels_for_object(self.team) is False

    def test_ac_object_default_response(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        assert self.user_access_control.access_level_for_object(self.team) == "admin"
        assert self.user_access_control.check_access_level_for_object(self.team, "admin") is True
        assert self.other_user_access_control.access_level_for_object(self.team) == "admin"
        assert self.other_user_access_control.check_access_level_for_object(self.team, "admin") is True
        resource_access = self.user_access_control.access_level_for_resource("project")
        assert resource_access and resource_access.access_level == "admin"
        resource_access = self.other_user_access_control.access_level_for_resource("project")
        assert resource_access and resource_access.access_level == "admin"
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

    def test_project_default_survives_a_resource_level_project_rule(self):
        # A rule about "project" written without a resource_id is not a shape the product writes,
        # and enforcement never reads it. It must not send the walk to the resource tier, which
        # answers with the built-in project default and would promote everyone to admin
        self._create_access_control(resource="project", resource_id=self.team.id, access_level="member")
        self._create_access_control(resource="project", resource_id=None, access_level="none")
        self._clear_uac_caches()

        assert self.user_access_control.get_user_access_level(self.team) == "member"

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
        resource_access = self.user_access_control.access_level_for_resource("dashboard")
        assert resource_access and resource_access.access_level == "manager"
        resource_access = self.other_user_access_control.access_level_for_resource("dashboard")
        assert resource_access and resource_access.access_level == "editor"

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

        # Enable access control & role-based access for tests
        self.organization.available_product_features = [
            {"key": "access_control", "name": "access_control"},
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

    def test_filtering_ignores_rules_without_entitlement(self):
        # Global "none" rule on file_b (user is not its creator)
        AccessControl.objects.create(
            team=self.team,
            resource="my_resource",
            resource_id="def",
            access_level="none",
        )

        # Sanity: with the entitlement the rule is enforced (file_b hidden)
        self.assertCountEqual(
            [self.file_a],
            self.user_access_control.filter_and_annotate_file_system_queryset(FileSystem.objects.all()),
        )

        # Downgrade: drop the access_control entitlement -> stale rule must be ignored
        self.organization.available_product_features = []
        self.organization.save()

        fresh_uac = UserAccessControl(self.user, self.team)
        self.assertCountEqual(
            [self.file_a, self.file_b],
            fresh_uac.filter_and_annotate_file_system_queryset(FileSystem.objects.all()),
        )


@pytest.mark.ee
class TestUserAccessControlSerializer(BaseUserAccessControlTest):
    def setUp(self):
        super().setUp()
        # We'll use Dashboard as a sample resource object
        from products.dashboards.backend.models.dashboard import Dashboard

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

    def test_object_access_resolves_when_access_control_has_no_team(self):
        # A create request builds the access control with team=None (no team exists yet). Serializing
        # the create response must resolve the object's level from the organization scope instead of
        # raising AttributeError on the missing team.
        uac = UserAccessControl(user=self.user_with_no_role, team=None, organization_id=self.organization.id)

        # user_with_no_role is a plain member and did not create self.team, so resolution falls through
        # to the object-level lookup that would otherwise read the absent team. With no restricting
        # access control it resolves to the project default rather than raising.
        access_level = uac.get_user_access_level(self.team)
        assert access_level == "admin"

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
        from products.feature_flags.backend.models.feature_flag import FeatureFlag

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
        from products.notebooks.backend.models import Notebook

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
        from products.product_analytics.backend.facade.models import Insight

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
        from products.notebooks.backend.models import Notebook

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
        from products.notebooks.backend.models import Notebook

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
        from products.notebooks.backend.models import Notebook

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

    def test_filter_queryset_ignores_rules_without_entitlement(self):
        from products.notebooks.backend.models import Notebook

        # Member-level "none" rule blocking notebook_2 for the user
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_2.id),
            access_level="none",
            organization_member=self.organization_membership,
        )

        # Sanity: with the entitlement the rule is enforced
        self._clear_uac_caches()
        enforced_ids = list(
            self.user_access_control.filter_queryset_by_access_level(Notebook.objects.all()).values_list(
                "id", flat=True
            )
        )
        assert self.notebook_2.id not in enforced_ids

        # Downgrade: drop the access_control entitlement -> stale rule must be ignored
        self.organization.available_product_features = []
        self.organization.save()

        fresh_uac = UserAccessControl(self.user, self.team)
        filtered_ids = list(
            fresh_uac.filter_queryset_by_access_level(Notebook.objects.all()).values_list("id", flat=True)
        )
        assert self.notebook_1.id in filtered_ids
        assert self.notebook_2.id in filtered_ids
        assert self.notebook_3.id in filtered_ids

    def test_blocked_resource_ids_by_scope_ignores_rules_without_entitlement(self):
        # Member-level "none" rule blocking notebook_2 for the user
        self._create_access_control(
            resource="notebook",
            resource_id=str(self.notebook_2.id),
            access_level="none",
            organization_member=self.organization_membership,
        )

        # Sanity: with the entitlement the object is reported as blocked
        self._clear_uac_caches()
        assert str(self.notebook_2.id) in self.user_access_control.blocked_resource_ids_by_scope.get("notebook", set())

        # Downgrade: drop the access_control entitlement -> stale rule must be ignored
        self.organization.available_product_features = []
        self.organization.save()

        fresh_uac = UserAccessControl(self.user, self.team)
        assert fresh_uac.blocked_resource_ids_by_scope == {}

    @parameterized.expand(
        [
            (
                "include_all_if_admin lists default-none dashboard for org admin (issue #44364)",
                True,
                True,
            ),
            (
                "include_all_if_admin false keeps blocked default-none dashboards out of list for org admin",
                False,
                False,
            ),
        ]
    )
    def test_organization_admin_dashboard_list_respects_include_all_if_admin_flag(
        self, _name: str, include_all_if_admin: bool, expect_dashboard_in_results: bool
    ) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        dashboard = Dashboard.objects.create(team=self.team, created_by=self.other_user)
        self._create_access_control(
            resource="dashboard",
            resource_id=str(dashboard.id),
            access_level="none",
        )

        self._clear_uac_caches()
        uac = UserAccessControl(self.user, self.team)
        filtered = uac.filter_queryset_by_access_level(
            Dashboard.objects.filter(team=self.team),
            include_all_if_admin=include_all_if_admin,
        )
        ids = list(filtered.values_list("id", flat=True))
        if expect_dashboard_in_results:
            assert dashboard.id in ids
        else:
            assert dashboard.id not in ids

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

        from products.notebooks.backend.models import Notebook

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
        resource_access = self.user_access_control.access_level_for_resource("session_recording_playlist")
        assert resource_access and resource_access.access_level == "viewer"
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
        resource_access = self.user_access_control.access_level_for_resource("session_recording_playlist")
        assert resource_access and resource_access.access_level == "editor"
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
        resource_access = self.user_access_control.access_level_for_resource("session_recording_playlist")
        assert resource_access and resource_access.access_level == "manager"
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
        resource_access = self.user_access_control.access_level_for_resource("session_recording_playlist")
        assert resource_access and resource_access.access_level == "none"
        assert self.user_access_control.check_access_level_for_resource("session_recording_playlist", "viewer") is False

    def test_support_ticket_rule_does_not_gate_the_posthog_ai_conversation_scope(self):
        """`conversation` must not inherit from `ticket`.

        `conversation` is the scope object of PostHog AI's ConversationViewSet (ee/api/conversation.py)
        and nothing else uses it — Support's own viewsets declare `ticket` directly. Sending a message
        is a POST, so it requires `editor`: while `conversation` inherited from `ticket`, a project
        restricting Support tickets to `viewer` lost PostHog AI entirely for every non-admin member.
        """
        assert "conversation" not in RESOURCE_INHERITANCE_MAP

        self._create_access_control(
            resource="ticket",
            resource_id=None,
            access_level="viewer",
            organization_member=self.organization_membership,
        )
        self._clear_uac_caches()

        # The Support restriction still applies to Support.
        assert self.user_access_control.check_access_level_for_resource("ticket", "viewer") is True
        assert self.user_access_control.check_access_level_for_resource("ticket", "editor") is False

        # PostHog AI is untouched by it.
        conversation_access = self.user_access_control.access_level_for_resource("conversation")
        assert conversation_access and conversation_access.access_level == "editor"
        assert self.user_access_control.check_access_level_for_resource("conversation", "editor") is True


@pytest.mark.ee
class TestFieldLevelAccessControl(BaseUserAccessControlTest):
    def test_field_access_control_mapping_exists(self):
        """Test that field access control mappings are properly configured"""
        team_mappings = get_field_access_control_map(Team)

        # Verify session recording fields are mapped
        assert "session_recording_opt_in" in team_mappings
        assert team_mappings["session_recording_opt_in"] == ("project", "admin")
        assert "session_recording_sample_rate" in team_mappings
        assert team_mappings["session_recording_sample_rate"] == ("project", "admin")

    def test_field_validation_blocks_without_access(self):
        """Test that field validation blocks updates without proper access"""
        from rest_framework.exceptions import ValidationError

        # Set project access to "member" (default for all project members)
        self._create_access_control(resource="project", resource_id=str(self.team.id), access_level="member")
        self._clear_uac_caches()

        # Create a mock serializer with access control mixin
        class TeamSerializer(UserAccessControlSerializerMixin):
            pass

        # Create serializer with team instance
        view_mock = type("view", (), {"user_access_control": self.user_access_control})()
        serializer = TeamSerializer(instance=self.team, context={"view": view_mock})

        # Try to modify a protected field - should raise validation error
        # session_recording_opt_in requires "admin" access to project, but user only has "member"
        attrs = {"session_recording_opt_in": True}
        with pytest.raises(ValidationError) as exc_info:
            serializer.validate(attrs)

        detail = exc_info.value.detail
        assert isinstance(detail, dict), f"Expected dict but got {type(detail)}"
        assert "session_recording_opt_in" in detail
        # The error is a list, get the actual message
        error_detail = detail["session_recording_opt_in"]
        error_msg = str(error_detail[0]) if isinstance(error_detail, list) else str(error_detail)
        assert "admin access to projects" in error_msg, f"Got error message: {error_msg!r}"

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


class TestAccessControlMissingEE(BaseTest):
    """Verify that UserAccessControl methods don't crash when the ee module is not installed."""

    def setUp(self):
        super().setUp()
        self.uac = UserAccessControl(self.user, self.team, self.organization.id)

    @patch("products.access_control.backend.facade.user_access_control.EE_AVAILABLE", False)
    def test_get_access_controls_returns_empty(self):
        filters = {"team_id": self.team.id, "resource": "dashboard", "resource_id": None}
        assert self.uac._get_access_controls(filters) == []

    @patch("products.access_control.backend.facade.user_access_control.EE_AVAILABLE", False)
    def test_preload_access_levels_does_not_crash(self):
        self.uac.preload_access_levels(team=self.team, resource="dashboard")

    @patch("products.access_control.backend.facade.user_access_control.EE_AVAILABLE", False)
    def test_preload_object_access_controls_does_not_crash(self):
        dashboard = Dashboard.objects.create(team=self.team, name="test")
        self.uac.preload_object_access_controls([dashboard])

    @patch("products.access_control.backend.facade.user_access_control.EE_AVAILABLE", False)
    def test_filter_and_annotate_file_system_queryset_returns_unfiltered(self):
        qs = FileSystem.objects.filter(team=self.team)
        result = self.uac.filter_and_annotate_file_system_queryset(qs)
        assert list(result) == list(qs)


class TestBlockedResourceIdsByScope(BaseTest):
    """
    Tests the deny-set precedence used by HogQL system tables.

    These exercise UserAccessControl.blocked_resource_ids_by_scope directly,
    which is also the single source of truth for the HogQL printer guard and
    the cache-key fingerprint in query_runner.py.
    """

    def setUp(self):
        super().setUp()
        from posthog.constants import AvailableFeature

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        self.membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        self.membership.level = OrganizationMembership.Level.MEMBER
        self.membership.save()

        self.uac = UserAccessControl(self.user, self.team)

    def _blocked(self, resource="dashboard") -> frozenset[str]:
        return self.uac.blocked_resource_ids_by_scope.get(resource, frozenset())

    def test_empty_for_org_admin(self):
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        self.uac = UserAccessControl(self.user, self.team)
        assert self._blocked() == set()

    def test_no_object_overrides_means_no_blocked_ids(self):
        assert self._blocked() == set()

    def test_object_default_none_blocks_object(self):
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="none",
        )
        assert "42" in self._blocked()

    def test_object_default_editor_allows_object(self):
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="editor",
        )
        assert "42" not in self._blocked()

    def test_object_default_none_with_member_editor_override_allows(self):
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="none",
        )
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="editor",
            organization_member=self.membership,
        )
        assert "42" not in self._blocked()

    def test_object_default_editor_with_member_none_blocks(self):
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="editor",
        )
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="42",
            access_level="none",
            organization_member=self.membership,
        )
        assert "42" in self._blocked()

    def test_multiple_objects_mixed_access(self):
        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id="10", access_level="none")
        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id="20", access_level="editor")
        AccessControl.objects.create(team=self.team, resource="dashboard", resource_id="30", access_level="none")
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id="30",
            access_level="editor",
            organization_member=self.membership,
        )
        assert self._blocked() == {"10"}


@pytest.mark.ee
class TestUserAccessControlFallbackParent(BaseUserAccessControlTest):
    """Resolution through RESOURCE_FALLBACK_MAP: a synced table falls back to the source that syncs it."""

    def setUp(self):
        super().setUp()
        self.membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        self.source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id="src",
            connection_id="conn",
            destination_id="dest",
            source_type="Stripe",
            prefix="test",
        )
        self.sourced_table = DataWarehouseTable.objects.create(
            name="customers", format="Parquet", team=self.team, external_data_source=self.source, columns={}
        )
        self.self_managed_table = DataWarehouseTable.objects.create(
            name="uploads", format="Parquet", team=self.team, columns={}
        )

    def _apply(self, rules, table):
        # The four places a rule can be written about this table. The ladder exists because these are
        # different statements: "this source" is not "all sources", and neither is "all tables".
        targets = {
            "this_table": ("warehouse_table", str(table.id)),
            "this_source": ("external_data_source", str(self.source.id)),
            "all_tables": ("warehouse_objects", None),
            "all_sources": ("external_data_source", None),
        }
        for target, level in rules.items():
            resource, resource_id = targets[target]
            self._create_access_control(
                resource=resource, resource_id=resource_id, access_level=level, organization_member=self.membership
            )
        self._clear_uac_caches()

    def _level(self, table):
        return self.user_access_control.get_user_access_level(table)

    @parameterized.expand(
        [
            # A rule about a source reaches the tables it syncs, written either way round.
            ("source_reaches_its_tables", {"this_source": "none"}, "none"),
            ("all_sources_reaches_sourced_tables", {"all_sources": "none"}, "none"),
            # The table's own rule is more specific than its source's, in both directions.
            ("table_grant_beats_source_deny", {"this_source": "none", "this_table": "editor"}, "editor"),
            ("table_deny_beats_source_grant", {"this_source": "editor", "this_table": "none"}, "none"),
            # "All tables" is more specific than "all sources", so a broad table grant isn't capped
            # by a source denial - which lets an editor on tables sync a schema they only view.
            ("all_tables_beats_all_sources", {"all_sources": "none", "all_tables": "viewer"}, "viewer"),
            # ...and one named source is more specific than "all tables".
            ("one_source_beats_all_tables", {"this_source": "none", "all_tables": "editor"}, "none"),
        ]
    )
    def test_sourced_table_resolution(self, _name, rules, expected):
        self._apply(rules, self.sourced_table)

        assert self._level(self.sourced_table) == expected

    @parameterized.expand(
        [
            # A self-managed table has no source, so no rule about sources may reach it. Without this
            # skip, restricting sources would silently lock every S3 table and direct connection that
            # no source has ever touched.
            ("all_sources_cannot_reach_it", {"all_sources": "none"}, "editor"),
            ("one_source_cannot_reach_it", {"this_source": "none"}, "editor"),
            # The rules that do apply to it still govern it - the skip isn't switching access off.
            ("all_tables_still_governs_it", {"all_tables": "none"}, "none"),
            ("its_own_rule_still_governs_it", {"this_table": "viewer"}, "viewer"),
        ]
    )
    def test_self_managed_table_skips_the_source(self, _name, rules, expected):
        self._apply(rules, self.self_managed_table)

        assert self._level(self.self_managed_table) == expected

    def _apply_for_everyone(self, rules, table):
        # Same ladder as _apply, but rows that apply to every member
        targets = {
            "this_table": ("warehouse_table", str(table.id)),
            "this_source": ("external_data_source", str(self.source.id)),
            "all_tables": ("warehouse_objects", None),
            "all_sources": ("external_data_source", None),
        }
        for target, level in rules.items():
            resource, resource_id = targets[target]
            self._create_access_control(resource=resource, resource_id=resource_id, access_level=level)
        self._clear_uac_caches()

    def _resolve(self, table, uac=None):
        uac = uac or self.user_with_no_role_access_control
        rows = uac._get_access_controls(uac._access_controls_filters_for_object("warehouse_table", str(table.id)))
        return uac._object_access_level_from_rows(
            "warehouse_table", rows, fallback_parent_id=UserAccessControl._fallback_parent_id(table, "warehouse_table")
        )

    @parameterized.expand(
        [
            ("system_default_when_nothing_set", {}, ("editor", "system_default", None, "warehouse_objects"), None),
            (
                "source_default",
                {"this_source": "viewer"},
                ("viewer", "parent_object", "default", "external_data_source"),
                "source",
            ),
            ("tables_wide", {"all_tables": "viewer"}, ("viewer", "resource", "default", "warehouse_objects"), None),
            (
                "sources_wide",
                {"all_sources": "viewer"},
                ("viewer", "parent_resource", "default", "external_data_source"),
                None,
            ),
            ("object_default", {"this_table": "viewer"}, ("viewer", "object", "default", "warehouse_table"), "table"),
        ]
    )
    def test_resolution_reports_its_source(self, _name, rules, expected, expected_id_of):
        # The levels are pinned elsewhere; this pins the attribution the UI will render, so a
        # reordered or mislabeled tier fails here instead of shipping a wrong "Based on …"
        self._apply_for_everyone(rules, self.sourced_table)

        access = self._resolve(self.sourced_table)
        assert access is not None
        actual = (
            access.access_level,
            access.source,
            access.source_subject,
            access.source_resource,
        )
        assert actual == expected
        expected_ids = {None: None, "source": str(self.source.id), "table": str(self.sourced_table.id)}
        assert access.source_resource_id == expected_ids[expected_id_of]

    def test_creator_access_follows_the_subject_not_the_requester(self):
        # A subject resolves someone else's access, so the creator bypass must be theirs. Taking it
        # from the requesting user would hand every subject the access of whatever the requester made
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        other = User.objects.create_and_join(self.organization, "subject-creator@posthog.com", None)
        other_membership = other.organization_memberships.get(organization=self.organization)

        for_other = SubjectAccessControl(self.user, self.team, member=other_membership)
        assert for_other.get_user_access_level(dashboard) != "manager"

        dashboard.created_by = other
        dashboard.save()
        assert (
            SubjectAccessControl(self.user, self.team, member=other_membership).get_user_access_level(dashboard)
            == "manager"
        )

    def test_inherited_access_for_a_subject(self):
        # The inherited level is "what would this subject have without their override": the walk
        # runs over the subject's rules with their own row on the object left out, and a member
        # keeps the bypasses enforcement would still give them
        role = Role.objects.create(name="Data", organization=self.organization)
        table = self.sourced_table
        self._create_access_control(resource="warehouse_table", resource_id=str(table.id), access_level="viewer")
        self._create_access_control(
            resource="warehouse_table",
            resource_id=str(table.id),
            access_level="none",
            organization_member=self.membership,
        )
        self._create_access_control(
            resource="warehouse_table", resource_id=str(table.id), access_level="none", role=role
        )
        self._clear_uac_caches()

        default_access = SubjectAccessControl(self.user, self.team).inherited_access_for_object(table)
        assert default_access is not None
        assert (default_access.access_level, default_access.source) == ("editor", "system_default")

        member_access = SubjectAccessControl(self.user, self.team, member=self.membership).inherited_access_for_object(
            table
        )
        assert member_access is not None
        assert (member_access.access_level, member_access.source, member_access.source_subject) == (
            "viewer",
            "object",
            "default",
        )

        role_access = SubjectAccessControl(self.user, self.team, role_id=str(role.id)).inherited_access_for_object(
            table
        )
        assert role_access is not None
        assert (role_access.access_level, role_access.source, role_access.source_subject) == (
            "viewer",
            "object",
            "default",
        )

        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        admin_access = SubjectAccessControl(self.user, self.team, member=self.membership).inherited_access_for_object(
            table
        )
        assert admin_access is not None
        assert (admin_access.access_level, admin_access.source) == ("manager", "org_admin")

    def test_precheck_outcomes_report_their_source(self):
        resolved, access = self.user_access_control._object_access_level_precheck("warehouse_table", is_creator=True)
        assert resolved and access is not None
        assert (access.access_level, access.source) == ("manager", "creator")

        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        resolved, access = UserAccessControl(self.user, self.team)._object_access_level_precheck(
            "warehouse_table", is_creator=False
        )
        assert resolved and access is not None
        assert (access.access_level, access.source) == ("manager", "org_admin")

        resolved, access = self.user_with_no_role_access_control._object_access_level_precheck(
            "organization", is_creator=False
        )
        assert resolved and access is not None
        assert (access.access_level, access.source) == ("member", "org_membership")

    def test_tie_between_member_and_role_reports_the_member(self):
        self._create_access_control(
            resource="warehouse_table",
            resource_id=str(self.sourced_table.id),
            access_level="editor",
            organization_member=self.membership,
        )
        self._create_access_control(
            resource="warehouse_table", resource_id=str(self.sourced_table.id), access_level="editor", role=self.role_a
        )
        self._clear_uac_caches()

        access = self._resolve(self.sourced_table, self.user_access_control)
        assert access is not None
        assert (access.access_level, access.source, access.source_subject) == (
            "editor",
            "object",
            "member",
        )

    def test_resource_resolution_reports_its_source(self):
        self._create_access_control(resource="warehouse_objects", access_level="viewer")
        self._create_access_control(resource="warehouse_objects", access_level="editor", role=self.role_a)
        self._clear_uac_caches()

        access = self.user_access_control.access_level_for_resource("warehouse_table")
        assert access is not None
        # Also pins the inheritance redirect: a table's resource rules are the warehouse_objects ones
        assert (
            access.access_level,
            access.source,
            access.source_subject,
            access.source_resource,
        ) == ("editor", "resource", "role", "warehouse_objects")

    def test_source_denial_does_not_leak_across_sources(self):
        other_source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id="src2",
            connection_id="conn2",
            destination_id="dest2",
            source_type="Stripe",
            prefix="other",
        )
        other_table = DataWarehouseTable.objects.create(
            name="invoices", format="Parquet", team=self.team, external_data_source=other_source, columns={}
        )
        self._apply({"this_source": "none"}, self.sourced_table)

        assert self._level(self.sourced_table) == "none"
        assert self._level(other_table) == "editor"
