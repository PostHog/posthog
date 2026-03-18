import uuid

import pytest
from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl

from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource

try:
    from ee.models.rbac.access_control import AccessControl
    from ee.models.rbac.role import Role, RoleMembership
except ImportError:
    pass


@pytest.mark.ee
class TestExternalDataSourceAccessControl(APIBaseTest):
    def setUp(self):
        super().setUp()

        # Enable access control features
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

        # Create test users
        self.viewer_user = User.objects.create_and_join(self.organization, "viewer@posthog.com", "testtest")
        self.editor_user = User.objects.create_and_join(self.organization, "editor@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(self.organization, "noaccess@posthog.com", "testtest")

        # Create a test source
        self.source = self._create_external_data_source()
        self.schema = self._create_external_data_schema(self.source.id)

    def _create_external_data_source(self, created_by=None) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=created_by or self.user,
            prefix="test",
            job_inputs={
                "stripe_secret_key": "sk_test_123",
            },
        )

    def _create_external_data_schema(self, source_id) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name="Customers", team_id=self.team.pk, source_id=source_id, table=None
        )

    def _create_access_control(self, user, resource="external_data_source", resource_id=None, access_level="viewer"):
        """Helper to create access control for a user"""
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member=membership,
        )

    def _create_project_default_access_control(self, access_level="none"):
        """Helper to create project-default access control (applies to all users without explicit access)"""
        return AccessControl.objects.create(
            team=self.team,
            resource="external_data_source",
            resource_id=None,
            access_level=access_level,
            organization_member=None,
            role=None,
        )

    # --- Viewer Access Level Tests ---

    def test_viewer_can_list_sources(self):
        """Test that a user with viewer access can list sources"""
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve_source(self):
        """Test that a user with viewer access can retrieve a source"""
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.source.id))

    def test_viewer_cannot_delete_source(self):
        """Test that a user with viewer access cannot delete a source"""
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("editor", response.json()["detail"].lower())

    def test_viewer_cannot_update_source(self):
        """Test that a user with viewer access cannot update a source"""
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/",
            data={"description": "Updated description"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_reload_source(self):
        """Test that a user with viewer access cannot reload a source"""
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/reload/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Editor Access Level Tests ---

    def test_editor_can_list_sources(self):
        """Test that a user with editor access can list sources"""
        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_retrieve_source(self):
        """Test that a user with editor access can retrieve a source"""
        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_update_source(self):
        """Test that a user with editor access can update a source"""
        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/",
            data={"description": "Updated description"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.source.refresh_from_db()
        self.assertEqual(self.source.description, "Updated description")

    def test_editor_can_delete_source(self):
        """Test that a user with editor access can delete a source"""
        self._create_access_control(self.editor_user, access_level="editor")

        self.client.force_login(self.editor_user)
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.source.refresh_from_db()
        self.assertTrue(self.source.deleted)

    # --- None Access Level Tests ---

    def test_none_access_cannot_list_sources(self):
        """Test that a user with no access at all gets 403 (not empty list)"""
        self._create_access_control(self.no_access_user, access_level="none")

        self.client.force_login(self.no_access_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        # When user has "none" resource access AND no specific object access, they get 403
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_none_access_cannot_retrieve_source(self):
        """Test that a user with no access cannot retrieve a source"""
        self._create_access_control(self.no_access_user, access_level="none")

        self.client.force_login(self.no_access_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Project Default Access Control Tests ---

    def test_project_default_none_blocks_list_without_specific_access(self):
        """Test that project-default 'none' access blocks list for users without specific object access"""
        self._create_project_default_access_control(access_level="none")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        # When user has "none" via project-default AND no specific object access, they get 403
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_explicit_access_overrides_project_default_none(self):
        """Test that explicit user access overrides project-default 'none'"""
        self._create_project_default_access_control(access_level="none")
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    # --- Object-Level Access Control Tests ---

    def test_specific_source_access_with_none_resource_access(self):
        """Test that a user can have access to specific sources only"""
        # Create another source
        source2 = self._create_external_data_source()

        # Set resource-level access to none
        self._create_access_control(self.viewer_user, access_level="none")

        # Give viewer access to only the first source
        self._create_access_control(
            self.viewer_user,
            resource="external_data_source",
            resource_id=str(self.source.id),
            access_level="viewer",
        )

        self.client.force_login(self.viewer_user)

        # Should be able to access the first source
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should not be able to access the second source
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source2.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_filtered_list_with_mixed_access(self):
        """Test that list only returns sources the user has access to"""
        # Create another source that viewer won't have access to
        self._create_external_data_source()

        # Set resource-level access to none
        self._create_access_control(self.viewer_user, access_level="none")

        # Give viewer access to only the first source
        self._create_access_control(
            self.viewer_user,
            resource="external_data_source",
            resource_id=str(self.source.id),
            access_level="viewer",
        )

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Only the source with explicit access should be returned (not the other source)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(self.source.id))

    # --- Organization Admin Tests ---

    def test_org_admin_has_full_access(self):
        """Test that organization admins have full access to sources"""
        # Set project-default to none
        self._create_project_default_access_control(access_level="none")

        # Make user an org admin
        membership = OrganizationMembership.objects.get(user=self.editor_user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        self.client.force_login(self.editor_user)

        # Should be able to list
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        # Should be able to delete without explicit permissions
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    # --- Role-Based Access Tests ---

    def test_role_grants_editor_access(self):
        """Test that roles can be used to grant source access"""
        # Set project-default to none
        self._create_project_default_access_control(access_level="none")

        # Create a role with editor access to sources
        role = Role.objects.create(name="Source Editors", organization=self.organization)
        RoleMembership.objects.create(user=self.editor_user, role=role)

        # Grant the role editor access
        AccessControl.objects.create(team=self.team, resource="external_data_source", access_level="editor", role=role)

        self.client.force_login(self.editor_user)

        # Should be able to list
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        # Should be able to delete via role access
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_role_grants_viewer_access(self):
        """Test that roles can grant viewer access"""
        # Set project-default to none
        self._create_project_default_access_control(access_level="none")

        # Create a role with viewer access
        role = Role.objects.create(name="Source Viewers", organization=self.organization)
        RoleMembership.objects.create(user=self.viewer_user, role=role)

        # Grant the role viewer access
        AccessControl.objects.create(team=self.team, resource="external_data_source", access_level="viewer", role=role)

        self.client.force_login(self.viewer_user)

        # Should be able to list
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

        # Should NOT be able to delete
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- Creator Access Tests ---

    def test_creator_can_delete_other_users_blocked_source(self):
        """Test that a creator can delete their source even when others can't access it"""
        # Create a source by editor_user
        source = self._create_external_data_source(created_by=self.editor_user)

        # Set project-default to none (blocks access for everyone)
        self._create_project_default_access_control(access_level="none")

        # Give editor_user editor resource access (required for delete action)
        self._create_access_control(self.editor_user, access_level="editor")

        # Block viewer_user specifically from this source
        self._create_access_control(
            self.viewer_user,
            resource="external_data_source",
            resource_id=str(source.id),
            access_level="none",
        )

        self.client.force_login(self.editor_user)

        # Creator should be able to delete their own source
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{source.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_viewer_cannot_delete_regardless_of_creator(self):
        """Test that viewer resource access cannot delete, regardless of being creator or not"""
        # Create a source by viewer_user
        source = self._create_external_data_source(created_by=self.viewer_user)

        # Give viewer_user only viewer resource access
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)

        # Even though they created it, viewer resource access is not enough for DELETE action
        # (DELETE requires editor resource-level access)
        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{source.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_can_modify_access_controls(self):
        """Test that the creator can modify access controls for their sources"""
        # Create a source by editor_user
        source = self._create_external_data_source(created_by=self.editor_user)

        uac = UserAccessControl(self.editor_user, self.team)
        can_modify = uac.check_can_modify_access_levels_for_object(source)

        self.assertTrue(can_modify)

    # --- user_access_level Response Field Tests ---

    def test_user_access_level_in_list_response(self):
        """Test that user_access_level is included in list response"""
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertIn("user_access_level", results[0])

    def test_user_access_level_in_detail_response(self):
        """Test that user_access_level is included in detail response"""
        self._create_access_control(self.viewer_user, access_level="viewer")

        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("user_access_level", response.json())

    # --- Manager Access Tests ---

    def test_manager_can_access_access_controls_endpoint(self):
        """Test that a user with manager access can access the access_controls endpoint"""
        self._create_access_control(self.editor_user, access_level="manager")

        self.client.force_login(self.editor_user)
        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_sources/{self.source.id}/access_controls/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access_controls", response.json())
        self.assertIn("user_can_edit_access_levels", response.json())
