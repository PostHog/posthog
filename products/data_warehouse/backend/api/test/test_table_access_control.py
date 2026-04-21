import pytest
from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.data_warehouse.backend.models import DataWarehouseTable

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@pytest.mark.ee
class TestDataWarehouseTableAccessControl(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": AvailableFeature.ADVANCED_PERMISSIONS},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        self.viewer_user = User.objects.create_and_join(self.organization, "viewer@posthog.com", "testtest")
        self.editor_user = User.objects.create_and_join(self.organization, "editor@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(self.organization, "noaccess@posthog.com", "testtest")

        self.table = DataWarehouseTable.objects.create(
            name="sample_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern="s3://bucket/sample_table",
            columns={"name": "String"},
            created_by=self.user,
        )

    def _create_access_control(self, user, resource="warehouse_table", resource_id=None, access_level="viewer"):
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        return AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            access_level=access_level,
            organization_member=membership,
        )

    def _create_project_default(self, access_level="none"):
        return AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=None,
            access_level=access_level,
            organization_member=None,
            role=None,
        )

    def test_viewer_can_list(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_tables/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_tables/{self.table.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_cannot_update(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/warehouse_tables/{self.table.id}/",
            data={"name": "updated_table"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.delete(f"/api/environments/{self.team.pk}/warehouse_tables/{self.table.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_editor_can_update(self):
        self._create_access_control(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/warehouse_tables/{self.table.id}/",
            data={"name": "updated_table"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_none_access_cannot_retrieve(self):
        self._create_access_control(self.no_access_user, access_level="none")
        self.client.force_login(self.no_access_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_tables/{self.table.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_project_default_none_blocks_non_creator(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_tables/{self.table.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_list_filters_to_own_tables_when_other_is_blocked(self):
        other_user = User.objects.create_and_join(self.organization, "otheruser@posthog.com", "testtest")
        other_table = DataWarehouseTable.objects.create(
            name="other_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern="s3://bucket/other_table",
            columns={"name": "String"},
            created_by=other_user,
        )
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="warehouse_table",
            resource_id=str(other_table.id),
            access_level="none",
            organization_member=membership,
        )
        self.client.force_login(self.user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_tables/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [t["id"] for t in response.json()["results"]]
        self.assertIn(str(self.table.id), ids)
        self.assertNotIn(str(other_table.id), ids)

    def test_user_access_level_field_is_present(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(f"/api/environments/{self.team.pk}/warehouse_tables/{self.table.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json().get("user_access_level"), "viewer")
