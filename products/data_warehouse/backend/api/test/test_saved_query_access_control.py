import pytest
from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.data_warehouse.backend.models import DataWarehouseSavedQuery, DataWarehouseSavedQueryFolder

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@pytest.mark.ee
class TestDataWarehouseSavedQueryAccessControl(APIBaseTest):
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

        self.viewer_user = User.objects.create_and_join(self.organization, "viewer@posthog.com", "testtest")
        self.editor_user = User.objects.create_and_join(self.organization, "editor@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(self.organization, "noaccess@posthog.com", "testtest")

        self.saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=self.user,
        )

    def _create_access_control(self, user, resource="warehouse_view", resource_id=None, access_level="viewer"):
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member=membership,
        )

    def _create_project_default(self, resource="warehouse_view", access_level="none"):
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=None,
            access_level=access_level,
            organization_member=None,
            role=None,
        )

    def test_viewer_can_list(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_queries/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.saved_query.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_cannot_update(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.saved_query.id}/",
            data={"name": "updated"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.delete(
            f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.saved_query.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_editor_can_update(self):
        self._create_access_control(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.saved_query.id}/",
            data={"name": "updated_name"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_none_access_cannot_retrieve(self):
        self._create_access_control(self.no_access_user, access_level="none")
        self.client.force_login(self.no_access_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.saved_query.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_project_default_none_blocks_non_creator_retrieve(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.saved_query.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_list_filters_to_own_queries_when_explicit_viewer(self):
        # Creator has baseline viewer via explicit AC; the filter_queryset_by_access_level path still honors creator.
        other_user = User.objects.create_and_join(self.organization, "otheruser@posthog.com", "testtest")
        other_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="other_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=other_user,
        )
        # Block other_query specifically at object-level for the creator (self.user)
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=str(other_query.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(self.user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_queries/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [q["id"] for q in response.json()["results"]]
        # Own query still visible; the blocked other_query excluded
        self.assertIn(str(self.saved_query.id), ids)
        self.assertNotIn(str(other_query.id), ids)

    def test_non_creator_list_blocked_with_project_default_none(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_queries/")
        # With project-default none and no explicit access, the list endpoint returns 403.
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_explicit_viewer_access_allows_list_with_project_default_none(self):
        self._create_project_default(access_level="none")
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_queries/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_object_level_access_blocks_specific_query(self):
        # Give viewer project-level viewer, but set object-level none for this specific query.
        self._create_access_control(self.viewer_user, access_level="viewer")
        self._create_access_control(self.viewer_user, resource_id=str(self.saved_query.id), access_level="none")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.saved_query.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_user_access_level_field_is_present_in_response(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_queries/{self.saved_query.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json().get("user_access_level"), "viewer")


@pytest.mark.ee
class TestDataWarehouseSavedQueryFolderAccessControl(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        self.viewer_user = User.objects.create_and_join(self.organization, "viewer@posthog.com", "testtest")

        self.folder = DataWarehouseSavedQueryFolder.objects.create(
            team=self.team, name="Marketing", created_by=self.user
        )

    def _create_project_default(self, access_level="none"):
        return AccessControl.objects.create(
            team=self.team,
            resource="warehouse_view",
            resource_id=None,
            access_level=access_level,
            organization_member=None,
            role=None,
        )

    def test_folder_retrieve_respects_warehouse_view_default(self):
        # Folders share the warehouse_view resource; project-default none should block non-creators.
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_query_folders/{self.folder.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_folder_list_works_without_restrictions(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_saved_query_folders/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
