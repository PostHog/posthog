import pytest

from parameterized import parameterized
from rest_framework import status

from products.data_warehouse.backend.api.test._access_control_base import WarehouseAccessControlTestMixin


@pytest.mark.ee
class TestViewLinkAccessControl(WarehouseAccessControlTestMixin):
    # ViewLinkViewSet scope_object = "warehouse_view", which inherits from
    # "warehouse_objects" in RESOURCE_INHERITANCE_MAP — grant at the umbrella.
    resource = "warehouse_objects"

    def _list_url(self) -> str:
        return f"/api/environments/{self.team.pk}/warehouse_view_links/"

    def _join_payload(self) -> dict:
        return {
            "source_table_name": "events",
            "joining_table_name": "persons",
            "source_table_key": "uuid",
            "joining_table_key": "id",
            "field_name": "some_field",
            "configuration": None,
        }

    @parameterized.expand(
        [
            ("viewer", status.HTTP_403_FORBIDDEN),
            ("editor", status.HTTP_201_CREATED),
        ]
    )
    def test_create_join_access_level_matrix(self, access_level, expected_status):
        user = self.viewer_user if access_level == "viewer" else self.editor_user
        self._create_access_control(user, access_level=access_level)
        self.client.force_login(user)

        response = self.client.post(self._list_url(), data=self._join_payload())
        self.assertEqual(response.status_code, expected_status)

    def test_project_default_none_blocks_join_creation(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)

        response = self.client.post(self._list_url(), data=self._join_payload())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_can_list_joins(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
