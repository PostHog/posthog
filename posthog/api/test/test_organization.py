from datetime import timedelta
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import ANY, patch

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APIRequestFactory

from posthog.api.organization import OrganizationSerializer
from posthog.api.test.test_oauth import generate_rsa_key
from posthog.models import FeatureFlag, Organization, OrganizationMembership, Team
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.user_permissions import UserPermissions

from products.enterprise.backend.models.explicit_team_membership import ExplicitTeamMembership
from products.enterprise.backend.models.feature_flag_role_access import FeatureFlagRoleAccess
from products.enterprise.backend.models.rbac.access_control import AccessControl
from products.enterprise.backend.models.rbac.role import Role, RoleMembership


class TestOrganizationAPI(APIBaseTest):
    # Retrieving organization

    def test_get_current_organization(self):
        response = self.client.get("/api/organizations/@current")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        self.assertEqual(response_data["id"], str(self.organization.id))
        # By default, setup state is marked as completed
        self.assertEqual(response_data["available_product_features"], [])

        # DEPRECATED attributes
        self.assertNotIn("personalization", response_data)
        self.assertNotIn("setup", response_data)

    def test_get_current_team_fields(self):
        self.organization.setup_section_2_completed = False
        self.organization.save()
        Team.objects.create(organization=self.organization, is_demo=True, ingested_event=True)
        Team.objects.create(organization=self.organization, completed_snippet_onboarding=True)
        self.team.is_demo = True
        self.team.save()

        response_data = self.client.get("/api/organizations/@current").json()

        self.assertEqual(response_data["id"], str(self.organization.id))

    # Creating organizations

    def test_cant_create_organization_without_valid_license_on_self_hosted(self):
        with self.is_cloud(False):
            response = self.client.post("/api/organizations/", {"name": "Test"})
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(
                response.json(),
                {
                    "attr": None,
                    "code": "permission_denied",
                    "detail": "You must upgrade your PostHog plan to be able to create and manage multiple organizations.",
                    "type": "authentication_error",
                },
            )
            self.assertEqual(Organization.objects.count(), 1)
            response = self.client.post("/api/organizations/", {"name": "Test"})
            self.assertEqual(Organization.objects.count(), 1)

    def test_cant_create_organization_with_custom_plugin_level(self):
        with self.is_cloud(True):
            response = self.client.post("/api/organizations/", {"name": "Test", "plugins_access_level": 6})
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(Organization.objects.count(), 2)
            self.assertEqual(response.json()["plugins_access_level"], 3)

    # Updating organizations

    def test_update_organization_if_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.organization.name = self.CONFIG_ORGANIZATION_NAME
        self.organization.is_member_join_email_enabled = True
        self.organization.save()

        response_rename = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "QWERTY"})
        response_email = self.client.patch(
            f"/api/organizations/{self.organization.id}",
            {"is_member_join_email_enabled": False},
        )

        self.assertEqual(response_rename.status_code, status.HTTP_200_OK)
        self.assertEqual(response_email.status_code, status.HTTP_200_OK)

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "QWERTY")
        self.assertEqual(self.organization.is_member_join_email_enabled, False)

    def test_update_organization_if_owner(self):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        self.organization.name = self.CONFIG_ORGANIZATION_NAME
        self.organization.is_member_join_email_enabled = True
        self.organization.save()

        response_rename = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "QWERTY"})
        response_email = self.client.patch(
            f"/api/organizations/{self.organization.id}",
            {"is_member_join_email_enabled": False},
        )

        self.assertEqual(response_rename.status_code, status.HTTP_200_OK)
        self.assertEqual(response_email.status_code, status.HTTP_200_OK)

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "QWERTY")
        self.assertEqual(self.organization.is_member_join_email_enabled, False)

    def test_cannot_update_organization_if_not_owner_or_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        response_rename = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "ASDFG"})
        response_email = self.client.patch(
            f"/api/organizations/{self.organization.id}",
            {"is_member_join_email_enabled": False},
        )
        self.assertEqual(response_rename.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response_email.status_code, status.HTTP_403_FORBIDDEN)
        self.organization.refresh_from_db()
        self.assertNotEqual(self.organization.name, "ASDFG")

    def test_cant_update_plugins_access_level(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.organization.plugins_access_level = 3
        self.organization.save()

        response = self.client.patch(f"/api/organizations/{self.organization.id}", {"plugins_access_level": 9})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.plugins_access_level, 3)

    @patch("posthoganalytics.capture")
    def test_enforce_2fa_for_everyone(self, mock_capture):
        # Only admins should be able to enforce 2fa
        response = self.client.patch(f"/api/organizations/{self.organization.id}/", {"enforce_2fa": True})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.patch(f"/api/organizations/{self.organization.id}/", {"enforce_2fa": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.organization.refresh_from_db()
        self.assertEqual(self.organization.enforce_2fa, True)

        # Verify the capture event was called correctly
        mock_capture.assert_any_call(
            "organization 2fa enforcement toggled",
            distinct_id=self.user.distinct_id,
            properties={
                "enabled": True,
                "organization_id": str(self.organization.id),
                "organization_name": self.organization.name,
                "user_role": OrganizationMembership.Level.ADMIN,
            },
            groups={"instance": ANY, "organization": str(self.organization.id)},
        )

    def test_projects_outside_personal_api_key_scoped_organizations_not_listed(self):
        other_org, _, _ = Organization.objects.bootstrap(self.user)
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
            scoped_organizations=[other_org.id],
        )

        response = self.client.get("/api/organizations/", HTTP_AUTHORIZATION=f"Bearer {personal_api_key}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {org["id"] for org in response.json()["results"]},
            {str(other_org.id)},
            "Only the scoped organization should be listed, the other one should be excluded",
        )

    @override_settings(
        OAUTH2_PROVIDER={
            **settings.OAUTH2_PROVIDER,
            "OIDC_RSA_PRIVATE_KEY": generate_rsa_key(),
        }
    )
    def test_projects_outside_oauth_scoped_organizations_causes_401(self):
        # TODO: This should filter out the organizations to the scoped organizations, but it causes a 401 due to a bug in APIScopePermission for list endpoints.
        other_org, _, _ = Organization.objects.bootstrap(self.user)

        oauth_app = OAuthApplication.objects.create(
            name="Test OAuth App",
            client_id="test_client_id",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            user=self.user,
        )

        access_token = OAuthAccessToken.objects.create(
            application=oauth_app,
            user=self.user,
            token="test_oauth_token",
            scope="organization:read",
            expires=timezone.now() + timedelta(hours=1),
            scoped_organizations=[str(other_org.id)],
        )

        response = self.client.get("/api/organizations/", HTTP_AUTHORIZATION=f"Bearer {access_token.token}")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_organizations_and_verify_list(self):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

        # Create two additional organizations
        org2 = Organization.objects.bootstrap(self.user)[0]
        org3 = Organization.objects.bootstrap(self.user)[0]

        self.user.current_organization_id = self.organization.id
        self.user.save()

        # Verify we start with 3 organizations
        response = self.client.get("/api/organizations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 3)

        # Delete first organization and verify list
        response = self.client.delete(f"/api/organizations/{org2.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        response = self.client.get("/api/organizations/")
        self.assertEqual(len(response.json()["results"]), 2)
        org_ids = {org["id"] for org in response.json()["results"]}
        self.assertEqual(org_ids, {str(self.organization.id), str(org3.id)})

        # Delete second organization and verify list
        response = self.client.delete(f"/api/organizations/{org3.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        response = self.client.get("/api/organizations/")
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.organization.id))

        # Verify we can't delete the last organization
        response = self.client.delete(f"/api/organizations/{self.organization.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        response = self.client.get("/api/organizations/")
        self.assertEqual(
            response.json(),
            {
                "type": "invalid_request",
                "code": "not_found",
                "detail": "You need to belong to an organization.",
                "attr": None,
            },
        )


def create_organization(name: str) -> Organization:
    """
    Helper that just creates an organization. It currently uses the orm, but we
    could use either the api, or django admin to create, to get better parity
    with real world scenarios.
    """
    return Organization.objects.create(name=name)


class TestOrganizationPutPatchPermissions(APIBaseTest):
    """Test that PUT and PATCH methods have consistent permission behavior."""

    def test_put_organization_as_member_forbidden(self):
        """Test that members cannot update organization using PUT method."""
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.put(
            f"/api/organizations/{self.organization.id}",
            {"name": "Updated Name PUT"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_organization_as_member_forbidden(self):
        """Test that members cannot update organization using PATCH method."""
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.patch(
            f"/api/organizations/{self.organization.id}",
            {"name": "Updated Name PATCH"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_consistency_admin(self):
        """Test that PATCH method works consistently for admins."""
        # Test as admin - PATCH should work
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Test PATCH - only need to provide the fields we're updating
        response_patch = self.client.patch(
            f"/api/organizations/{self.organization.id}",
            {"name": "Admin Updated Name PATCH"},
        )
        self.assertEqual(response_patch.status_code, status.HTTP_200_OK)
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.name, "Admin Updated Name PATCH")

    def test_idor_protection_patch(self):
        """Test that users cannot modify organizations they don't belong to using PATCH."""
        # Create another organization with a different owner
        other_org, _, other_user = Organization.objects.bootstrap(self._create_user("other_user@posthog.com"))

        # Make current user an admin of their own org
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Try to modify other organization using PATCH - should fail
        # The exact status code (403 or 404) depends on permission implementation
        response_patch = self.client.patch(
            f"/api/organizations/{other_org.id}",
            {"name": "Hacked Name PATCH"},
        )
        # Should be either forbidden or not found - both indicate access is properly restricted
        self.assertIn(response_patch.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

        # Verify the other organization wasn't modified
        other_org.refresh_from_db()
        self.assertNotEqual(other_org.name, "Hacked Name PATCH")


class TestOrganizationSerializer(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.request = self.factory.get("/")
        self.request.user = self.user

        # Create a mock view with user_permissions
        class MockView:
            def __init__(self, user_permissions):
                self.user_permissions = user_permissions

        self.view = MockView(UserPermissions(self.user))
        self.context = {"request": self.request, "view": self.view}

    def test_get_teams_with_no_org(self):
        # Clear current_team reference before deleting organization
        self.user.current_team = None
        self.user.current_organization = None
        self.user.save()

        self.organization.delete()

        serializer = OrganizationSerializer(context=self.context)
        self.assertEqual(serializer.user_permissions.team_ids_visible_for_user, [])

    def test_get_teams_with_single_org_no_teams(self):
        # Delete default team created by APIBaseTest
        self.team.delete()

        serializer = OrganizationSerializer(self.organization, context=self.context)
        self.assertEqual(serializer.get_teams(self.organization), [])

    def test_get_teams_with_single_org_multiple_teams(self):
        team2 = Team.objects.create(organization=self.organization, name="Test Team 2")
        team3 = Team.objects.create(organization=self.organization, name="Test Team 3")

        serializer = OrganizationSerializer(self.organization, context=self.context)
        teams = serializer.get_teams(self.organization)

        self.assertEqual(len(teams), 3)
        team_names = {team["name"] for team in teams}
        self.assertEqual(team_names, {self.team.name, team2.name, team3.name})

    def test_get_teams_with_multiple_orgs(self):
        org2, _, _ = Organization.objects.bootstrap(self.user)
        team2 = Team.objects.create(organization=org2, name="Org 2 Team")

        serializer = OrganizationSerializer(self.organization, context=self.context)
        teams1 = serializer.get_teams(self.organization)
        teams2 = serializer.get_teams(org2)

        self.assertEqual(len(teams1), 1)
        self.assertEqual(teams1[0]["name"], self.team.name)

        self.assertEqual(len(teams2), 2)
        self.assertEqual(
            sorted([team["name"] for team in teams2]),
            sorted(["Default project", team2.name]),
        )


class TestOrganizationRbacMigrations(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Create some roles
        self.admin_role = Role.objects.create(
            name="Admin Role",
            organization=self.organization,
            feature_flags_access_level=37,
        )
        self.basic_role = Role.objects.create(
            name="Basic Role",
            organization=self.organization,
            feature_flags_access_level=21,
        )

        # Create test users with different permissions
        self.admin_user = self._create_user("rbac_admin+1@posthog.com", level=OrganizationMembership.Level.ADMIN)
        self.member_user = self._create_user("rbac_member+1@posthog.com")

        # Bind admin role to admin user
        RoleMembership.objects.create(
            role=self.admin_role,
            user=self.admin_user,
            organization_member=self.admin_user.organization_memberships.first(),
        )

    @patch("posthog.api.organization.report_organization_action")
    def test_migrate_feature_flags_rbac_as_admin(self, mock_report_action):
        self.client.force_login(self.admin_user)

        # Create a test feature flag
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.admin_user, key="test-flag", name="Test Flag"
        )
        FeatureFlagRoleAccess.objects.create(
            feature_flag=feature_flag,
            role=self.admin_role,
        )

        response = self.client.post(f"/api/organizations/{self.organization.id}/migrate_access_control/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], True)

        feature_flag_access = FeatureFlagRoleAccess.objects.first()
        self.assertIsNone(feature_flag_access)

        access_control = AccessControl.objects.get(resource="feature_flag")
        self.assertEqual(access_control.access_level, "editor")
        self.assertEqual(access_control.role, self.admin_role)
        self.assertEqual(access_control.resource, "feature_flag")
        self.assertEqual(access_control.resource_id, str(feature_flag.id))

        # Verify reporting calls
        mock_report_action.assert_any_call(
            self.organization, "rbac_team_migration_started", {"user": self.admin_user.distinct_id}
        )
        mock_report_action.assert_any_call(
            self.organization, "rbac_team_migration_completed", {"user": self.admin_user.distinct_id}
        )

    @patch("posthog.api.organization.report_organization_action")
    def test_migrate_feature_flags_rbac_with_specific_role_access(self, mock_report_action):
        self.client.force_login(self.admin_user)

        # Create a test feature flag
        feature_flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.admin_user, key="test-flag", name="Test Flag"
        )

        # Create specific role access
        FeatureFlagRoleAccess.objects.create(
            feature_flag=feature_flag,
            role=self.admin_role,
        )

        response = self.client.post(f"/api/organizations/{self.organization.id}/migrate_access_control/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], True)

        # Verify specific role access was migrated
        self.assertEqual(FeatureFlagRoleAccess.objects.count(), 0)
        access_control = AccessControl.objects.get(
            resource="feature_flag",
            resource_id=str(feature_flag.id),
            role=self.admin_role,
        )
        self.assertEqual(access_control.access_level, "editor")

        # Add verification of reporting calls at the end
        mock_report_action.assert_any_call(
            self.organization, "rbac_team_migration_started", {"user": self.admin_user.distinct_id}
        )
        mock_report_action.assert_any_call(
            self.organization, "rbac_team_migration_completed", {"user": self.admin_user.distinct_id}
        )

    @patch("posthog.api.organization.report_organization_action")
    def test_migrate_team_rbac_as_admin(self, mock_report_action):
        # Create a new team with access control enabled
        team_with_access_control = Team.objects.create(
            organization=self.organization, name="Team with Access Control", access_control=True
        )

        # Create inactive user
        self.inactive_user = self._create_user("rbac_inactive@posthog.com")
        self.inactive_user.is_active = False
        self.inactive_user.save()

        # Create users with different org membership levels
        self.org_admin = self._create_user("rbac_org_admin@posthog.com", level=OrganizationMembership.Level.ADMIN)
        self.org_member = self._create_user("rbac_org_member@posthog.com", level=OrganizationMembership.Level.MEMBER)

        self.client.force_login(self.admin_user)

        # Create explicit team memberships
        ExplicitTeamMembership.objects.create(
            team=team_with_access_control,
            parent_membership=cast(OrganizationMembership, self.inactive_user.organization_memberships.first()),
            level=ExplicitTeamMembership.Level.MEMBER,
        )
        ExplicitTeamMembership.objects.create(
            team=team_with_access_control,
            parent_membership=cast(OrganizationMembership, self.org_admin.organization_memberships.first()),
            level=ExplicitTeamMembership.Level.ADMIN,
        )
        ExplicitTeamMembership.objects.create(
            team=team_with_access_control,
            parent_membership=cast(OrganizationMembership, self.org_member.organization_memberships.first()),
            level=ExplicitTeamMembership.Level.MEMBER,
        )

        response = self.client.post(f"/api/organizations/{self.organization.id}/migrate_access_control/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], True)

        # Verify that inactive user's access was not migrated
        with self.assertRaises(AccessControl.DoesNotExist):
            AccessControl.objects.get(
                organization_member=cast(OrganizationMembership, self.inactive_user.organization_memberships.first())
            )

        # Verify that org admin's explicit team membership was not migrated
        with self.assertRaises(AccessControl.DoesNotExist):
            AccessControl.objects.get(
                organization_member=cast(OrganizationMembership, self.org_admin.organization_memberships.first())
            )

        # Verify that org member's access was migrated
        member_access = AccessControl.objects.get(
            organization_member=cast(OrganizationMembership, self.org_member.organization_memberships.first())
        )
        self.assertEqual(member_access.access_level, "member")
        self.assertEqual(member_access.resource, "project")
        self.assertEqual(member_access.resource_id, str(team_with_access_control.id))

        # Verify base team access control was created
        base_access = AccessControl.objects.get(team=team_with_access_control, organization_member__isnull=True)
        self.assertEqual(base_access.access_level, "none")
        self.assertEqual(base_access.resource, "project")
        self.assertEqual(base_access.resource_id, str(team_with_access_control.id))

        # Verify admin access control was created
        admin_access = AccessControl.objects.filter(
            team=team_with_access_control,
            organization_member=cast(OrganizationMembership, self.org_admin.organization_memberships.first()),
            access_level="admin",
            resource="project",
            resource_id=str(team_with_access_control.id),
        )
        self.assertEqual(admin_access.count(), 0)

        # Verify member access control was created
        member_access = AccessControl.objects.get(
            team=team_with_access_control,
            organization_member=cast(OrganizationMembership, self.org_member.organization_memberships.first()),
            access_level="member",
            resource="project",
            resource_id=str(team_with_access_control.id),
        )
        self.assertIsNotNone(member_access)

        # Check that the team access control has been disabled
        team_with_access_control.refresh_from_db()
        self.assertFalse(team_with_access_control.access_control)

        # Add verification of reporting calls at the end
        mock_report_action.assert_any_call(
            self.organization, "rbac_team_migration_started", {"user": self.admin_user.distinct_id}
        )
        mock_report_action.assert_any_call(
            self.organization, "rbac_team_migration_completed", {"user": self.admin_user.distinct_id}
        )

    def test_migrate_team_rbac_as_member_without_permissions(self):
        self.member_user = self._create_user("rbac_member+3@posthog.com")
        self.client.force_login(self.member_user)

        response = self.client.post(f"/api/organizations/{self.organization.id}/migrate_access_control/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_migrate_team_rbac_wrong_organization(self):
        self.admin_user = self._create_user("rbac_admin+4@posthog.com", level=OrganizationMembership.Level.ADMIN)
        self.client.force_login(self.admin_user)

        other_org = Organization.objects.create(name="Other Org")

        response = self.client.post(f"/api/organizations/{other_org.id}/migrate_access_control/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("posthog.api.organization.report_organization_action")
    def test_migrate_both_feature_flags_and_team_rbac(self, mock_report_action):
        """Test that both feature flag and team RBAC migrations can be performed in a single call."""
        # Create a new team with access control enabled
        team_with_access_control = Team.objects.create(
            organization=self.organization, name="Team with Access Control", access_control=True
        )

        # Set up users
        self.admin_user = self._create_user("rbac_admin+5@posthog.com", level=OrganizationMembership.Level.ADMIN)
        self.member_user = self._create_user("rbac_member+5@posthog.com")

        self.client.force_login(self.admin_user)

        # Create explicit team memberships
        ExplicitTeamMembership.objects.create(
            team=team_with_access_control,
            parent_membership=cast(OrganizationMembership, self.admin_user.organization_memberships.first()),
            level=ExplicitTeamMembership.Level.ADMIN,
        )
        ExplicitTeamMembership.objects.create(
            team=team_with_access_control,
            parent_membership=cast(OrganizationMembership, self.member_user.organization_memberships.first()),
            level=ExplicitTeamMembership.Level.MEMBER,
        )

        # Create feature flags with role access
        feature_flags = []
        for i in range(2):
            feature_flag = FeatureFlag.objects.create(
                team=team_with_access_control,
                created_by=self.admin_user,
                key=f"test-flag-{i}",
                name=f"Test Flag {i}",
            )
            feature_flags.append(feature_flag)
            FeatureFlagRoleAccess.objects.create(
                feature_flag=feature_flag,
                role=self.admin_role,
            )

        # Perform migration
        response = self.client.post(f"/api/organizations/{self.organization.id}/migrate_access_control/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], True)

        # Verify feature flag access controls
        self.assertEqual(FeatureFlagRoleAccess.objects.count(), 0)
        self.assertEqual(AccessControl.objects.filter(resource="feature_flag").count(), 2)

        for feature_flag in feature_flags:
            access_control = AccessControl.objects.get(resource="feature_flag", resource_id=str(feature_flag.id))
            self.assertEqual(access_control.access_level, "editor")
            self.assertEqual(access_control.role, self.admin_role)

        # Verify team access controls
        self.assertEqual(ExplicitTeamMembership.objects.count(), 0)
        base_access = AccessControl.objects.get(
            team=team_with_access_control,
            organization_member__isnull=True,
            access_level="none",
            resource="project",
            resource_id=str(team_with_access_control.id),
        )
        self.assertIsNotNone(base_access)

        admin_access = AccessControl.objects.filter(
            team=team_with_access_control,
            organization_member=cast(OrganizationMembership, self.admin_user.organization_memberships.first()),
            access_level="admin",
            resource="project",
            resource_id=str(team_with_access_control.id),
        )
        # Shouldn't exist
        self.assertEqual(admin_access.count(), 0)

        member_access = AccessControl.objects.get(
            team=team_with_access_control,
            organization_member=cast(OrganizationMembership, self.member_user.organization_memberships.first()),
            access_level="member",
            resource="project",
            resource_id=str(team_with_access_control.id),
        )
        self.assertIsNotNone(member_access)

        # Verify total number of access controls
        # 2 feature flags + 2 team access controls (base + member)
        self.assertEqual(AccessControl.objects.count(), 4)

        # Add verification of reporting calls at the end
        mock_report_action.assert_any_call(
            self.organization, "rbac_team_migration_started", {"user": self.admin_user.distinct_id}
        )
        mock_report_action.assert_any_call(
            self.organization, "rbac_team_migration_completed", {"user": self.admin_user.distinct_id}
        )

    @patch("posthog.api.organization.report_organization_action")
    def test_migrate_team_rbac_fails_with_error(self, mock_report_action):
        """Test that errors during migration are properly handled and reported."""
        self.client.force_login(self.admin_user)

        with patch("posthog.api.organization.rbac_team_access_control_migration", side_effect=Exception("Test error")):
            response = self.client.post(f"/api/organizations/{self.organization.id}/migrate_access_control/")

            self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
            self.assertEqual(response.json(), {"status": False, "error": "An internal error has occurred."})

            # Verify error was reported
            mock_report_action.assert_any_call(
                self.organization, "rbac_team_migration_started", {"user": self.admin_user.distinct_id}
            )
            mock_report_action.assert_any_call(
                self.organization,
                "rbac_team_migration_failed",
                {"user": self.admin_user.distinct_id, "error": "Test error"},
            )
