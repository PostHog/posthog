"""Access control coverage for the non-core data warehouse viewsets.

Covers managed viewsets, the data_warehouse stats/provisioning endpoints, model paths,
data modeling jobs, and lineage — each gated under warehouse_view (reads) or
warehouse_view:write (write actions). Verifies viewer/editor/none rejection and
acceptance for the endpoints that actually get traffic.
"""

import pytest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.data_warehouse.backend.api.test._access_control_base import WarehouseAccessControlTestMixin
from products.data_warehouse.backend.models import DataWarehouseManagedViewSet, DataWarehouseSavedQuery

MANAGED_VIEWSET_KIND = "revenue_analytics"


@pytest.mark.ee
class TestDataWarehouseManagedViewSetAccessControl(WarehouseAccessControlTestMixin):
    """Hole 1: PUT managed_viewsets/{kind}/ used to bypass AC entirely."""

    resource = "warehouse_objects"

    def _detail_url(self) -> str:
        return f"/api/environments/{self.team.pk}/managed_viewsets/{MANAGED_VIEWSET_KIND}/"

    @parameterized.expand(
        [
            ("viewer", status.HTTP_403_FORBIDDEN),
            ("editor", status.HTTP_200_OK),
        ]
    )
    @patch(
        "products.data_warehouse.backend.models.datawarehouse_managed_viewset.DataWarehouseManagedViewSet.sync_views"
    )
    def test_enable_access_matrix(self, access_level, expected_status, mock_sync_views):
        # sync_views is heavy (builds HogQL Database, resolves revenue analytics views);
        # we only care about the AC decision here so mock it out.
        mock_sync_views.return_value = None
        user = self.viewer_user if access_level == "viewer" else self.editor_user
        self._create_access_control(user, access_level=access_level)
        self.client.force_login(user)

        response = self.client.put(self._detail_url(), data={"enabled": True}, content_type="application/json")
        self.assertEqual(response.status_code, expected_status)

    def test_disable_as_viewer_is_blocked(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.put(self._detail_url(), data={"enabled": False}, content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # No managed viewset row should have been created/destroyed.
        self.assertFalse(DataWarehouseManagedViewSet.objects.filter(team=self.team, kind=MANAGED_VIEWSET_KIND).exists())

    def test_project_default_none_blocks_read(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self._detail_url())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@pytest.mark.ee
class TestDataWarehouseViewSetAccessControl(WarehouseAccessControlTestMixin):
    """Hole 2: data_warehouse/* had a mix of reads + writes all ungated."""

    resource = "warehouse_objects"

    def _path(self, action_path: str) -> str:
        return f"/api/environments/{self.team.pk}/data_warehouse/{action_path}"

    def test_total_rows_stats_readable_by_viewer(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self._path("total_rows_stats/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_total_rows_stats_blocked_for_none(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self._path("total_rows_stats/"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_data_ops_dashboard_blocked_for_viewer(self):
        # data_ops_dashboard creates a Dashboard as a side effect, so require editor
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self._path("data_ops_dashboard/"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_data_ops_dashboard_allowed_for_editor(self):
        self._create_access_control(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.get(self._path("data_ops_dashboard/"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_provision_blocked_for_viewer(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            self._path("provision/"), data={"database_name": "x"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@pytest.mark.ee
class TestModelPathViewSetAccessControl(WarehouseAccessControlTestMixin):
    """Read-only DAG endpoints — viewer OK, none blocked."""

    resource = "warehouse_objects"

    def _list_url(self) -> str:
        return f"/api/projects/{self.team.pk}/warehouse_model_paths/"

    def test_viewer_can_list(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_project_default_none_blocks(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@pytest.mark.ee
class TestDataModelingJobViewSetAccessControl(WarehouseAccessControlTestMixin):
    """Read-only job listing — viewer OK, none blocked."""

    resource = "warehouse_objects"

    def _list_url(self) -> str:
        return f"/api/environments/{self.team.pk}/data_modeling_jobs/"

    def test_viewer_can_list(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_project_default_none_blocks(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self._list_url())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@pytest.mark.ee
class TestLineageAccessControl(WarehouseAccessControlTestMixin):
    """Upstream lineage read — viewer OK, none blocked."""

    resource = "warehouse_objects"

    def setUp(self):
        super().setUp()
        self.saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="lineage_root",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=self.viewer_user,
        )

    def _url(self) -> str:
        return f"/api/environments/{self.team.pk}/lineage/get_upstream/?model_id={self.saved_query.id}"

    def test_viewer_can_read(self):
        self._create_access_control(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_project_default_none_blocks(self):
        self._create_project_default(access_level="none")
        self.client.force_login(self.viewer_user)

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
