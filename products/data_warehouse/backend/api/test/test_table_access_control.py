import pytest

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.data_warehouse.backend.api.test._access_control_base import WarehouseAccessControlTestMixin
from products.data_warehouse.backend.models import DataWarehouseTable

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@pytest.mark.ee
class TestDataWarehouseTableAccessControl(WarehouseAccessControlTestMixin):
    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        self.table = DataWarehouseTable.objects.create(
            name="sample_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern="s3://bucket/sample_table",
            columns={"name": "String"},
            created_by=self.user,
        )

    def _list_url(self) -> str:
        return f"/api/environments/{self.team.pk}/warehouse_tables/"

    def _detail_url(self) -> str:
        return f"/api/environments/{self.team.pk}/warehouse_tables/{self.table.id}/"

    @parameterized.expand(
        [
            # (access_level, method, expected_status, patch_body)
            ("viewer", "GET", status.HTTP_200_OK, None),
            ("viewer", "PATCH", status.HTTP_403_FORBIDDEN, {"name": "updated_table"}),
            ("viewer", "DELETE", status.HTTP_403_FORBIDDEN, None),
            ("editor", "GET", status.HTTP_200_OK, None),
            ("editor", "PATCH", status.HTTP_200_OK, {"name": "updated_table"}),
            ("none", "GET", status.HTTP_403_FORBIDDEN, None),
        ]
    )
    def test_access_level_matrix(self, access_level, method, expected_status, patch_body):
        user = (
            self.viewer_user
            if access_level == "viewer"
            else self.editor_user
            if access_level == "editor"
            else self.no_access_user
        )
        self._create_access_control(user, access_level=access_level)
        self.client.force_login(user)

        if method == "GET":
            response = self.client.get(self._detail_url())
        elif method == "PATCH":
            response = self.client.patch(self._detail_url(), data=patch_body)
        elif method == "DELETE":
            response = self.client.delete(self._detail_url())
        else:
            raise AssertionError(f"Unsupported method {method}")

        self.assertEqual(response.status_code, expected_status)

    def test_viewer_can_list(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._list_url()).status_code, status.HTTP_200_OK)

    def test_project_default_none_blocks_non_creator(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)
        self.assertEqual(self.client.get(self._detail_url()).status_code, status.HTTP_403_FORBIDDEN)

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
        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [t["id"] for t in response.json()["results"]]
        self.assertIn(str(self.table.id), ids)
        self.assertNotIn(str(other_table.id), ids)

    def test_user_access_level_field_is_present(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)
        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json().get("user_access_level"), "viewer")
