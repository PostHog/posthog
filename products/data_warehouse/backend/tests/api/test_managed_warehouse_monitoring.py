import json
from typing import cast

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.response import Response

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.presentation.managed_warehouse_monitoring import (
    ManagedWarehouseMonitoringSeriesQuerySerializer,
)
from products.warehouse_sources.backend.facade.testing import WarehouseAccessControlTestMixin


def _snapshot(organization_id: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "org_id": str(organization_id),
        "as_of": "2026-08-12T17:00:00Z",
        "warehouse": {"state": "ready"},
        "limits": {
            "max_workers": 4,
            "max_vcpus": 8,
            "default_worker_cpu": "2",
            "default_worker_memory": "8Gi",
            "default_worker_ttl_seconds": 1800,
            "default_worker_min_hot_idle": 1,
        },
        "totals": {
            "workers": 1,
            "allocated_cpu_cores": 2,
            "allocated_memory_bytes": 8_589_934_592,
            "active_sessions": 1,
            "running_queries": 1,
            "queued_connections": 0,
        },
        "workers": [
            {
                "id": 7,
                "state": "hot",
                "cpu": "2",
                "memory": "8Gi",
                "ttl_seconds": 900,
                "created_at": "2026-08-12T16:00:00Z",
                "last_heartbeat_at": "2026-08-12T16:59:59Z",
                "session": {
                    "protocol": "pg",
                    "state": "active",
                    "elapsed_ms": 1200,
                    "percentage": 42.5,
                    "rows": 100,
                    "total_rows": 1000,
                    "stalled": False,
                },
            }
        ],
        "coverage": {"cp_responders": 2, "cp_total": 2, "partial": False},
    }


def _series(organization_id: object, metric: str = "query_rate") -> dict[str, object]:
    return {
        "schema_version": 1,
        "org_id": str(organization_id),
        "metric": metric,
        "unit": "queries_per_second",
        "start": "2026-08-11T17:00:00Z",
        "end": "2026-08-12T17:00:00Z",
        "step_seconds": 60,
        "series": [
            {
                "labels": {"status": "success", "reason": "none"},
                "points": [{"timestamp": "2026-08-12T16:59:00Z", "value": 2.5}],
            }
        ],
    }


class TestManagedWarehouseMonitoringSeriesQuerySerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("unknown_metric", {"metric": "worker_states", "window": "1h"}, "metric"),
            ("removed_data_read_metric", {"metric": "s3_bytes_rate", "window": "1h"}, "metric"),
            ("unknown_window", {"metric": "query_rate", "window": "2h"}, "window"),
            ("missing_metric", {"window": "24h"}, "metric"),
        ]
    )
    def test_rejects_values_outside_the_allow_list(
        self,
        _name: str,
        query: dict[str, str],
        error_field: str,
    ) -> None:
        serializer = ManagedWarehouseMonitoringSeriesQuerySerializer(data=query)

        assert not serializer.is_valid()
        assert error_field in serializer.errors


class TestManagedWarehouseMonitoringAPI(APIBaseTest):
    def _snapshot_url(self) -> str:
        return f"/api/projects/{self.team.id}/data_warehouse/managed-warehouse-monitoring/"

    def _series_url(self, query: str = "metric=query_rate&window=6h") -> str:
        return f"/api/projects/{self.team.id}/data_warehouse/managed-warehouse-monitoring-timeseries/?{query}"

    @patch(
        "products.data_warehouse.backend.presentation.views.data_warehouse.managed_warehouse.monitoring_snapshot_for"
    )
    def test_snapshot_derives_the_organization_and_removes_unknown_fields(self, mock_snapshot: MagicMock) -> None:
        upstream = _snapshot(self.organization.id)
        upstream["bucket"] = "sensitive-bucket"
        worker = cast(dict[str, object], cast(list[object], upstream["workers"])[0])
        worker["pod_name"] = "sensitive-pod"
        worker["image"] = "sensitive-image"
        worker["owner_cp_instance_id"] = "sensitive-control-plane"
        session = cast(dict[str, object], worker["session"])
        session["user"] = "sensitive-user"
        mock_snapshot.return_value = Response(upstream, status=status.HTTP_200_OK)

        response = self.client.get(self._snapshot_url())

        assert response.status_code == status.HTTP_200_OK
        mock_snapshot.assert_called_once_with(str(self.organization.id))
        body = response.json()
        assert set(body) == {
            "schema_version",
            "org_id",
            "as_of",
            "warehouse",
            "limits",
            "totals",
            "workers",
            "coverage",
        }
        assert body["workers"][0]["id"] == "7"
        serialized = json.dumps(body)
        for forbidden in (
            "bucket",
            "sensitive-bucket",
            "pod_name",
            "sensitive-pod",
            "image",
            "sensitive-image",
            "owner_cp_instance_id",
            "sensitive-control-plane",
            "user",
            "sensitive-user",
        ):
            assert forbidden not in serialized

    @patch(
        "products.data_warehouse.backend.presentation.views.data_warehouse.managed_warehouse.monitoring_snapshot_for"
    )
    def test_snapshot_rejects_an_upstream_organization_mismatch(self, mock_snapshot: MagicMock) -> None:
        upstream = _snapshot("different-organization")
        upstream["secret"] = "must-not-leak"
        mock_snapshot.return_value = Response(upstream, status=status.HTTP_200_OK)

        response = self.client.get(self._snapshot_url())

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "different-organization" not in response.content.decode()
        assert "must-not-leak" not in response.content.decode()

    @patch(
        "products.data_warehouse.backend.presentation.views.data_warehouse.managed_warehouse.monitoring_snapshot_for"
    )
    def test_snapshot_accepts_workers_with_unavailable_resource_profiles(self, mock_snapshot: MagicMock) -> None:
        upstream = _snapshot(self.organization.id)
        worker = cast(dict[str, object], cast(list[object], upstream["workers"])[0])
        worker["cpu"] = ""
        worker["memory"] = ""
        mock_snapshot.return_value = Response(upstream, status=status.HTTP_200_OK)

        response = self.client.get(self._snapshot_url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workers"][0]["cpu"] == ""
        assert response.json()["workers"][0]["memory"] == ""

    @patch(
        "products.data_warehouse.backend.presentation.views.data_warehouse.managed_warehouse.monitoring_snapshot_for"
    )
    def test_snapshot_accepts_unavailable_query_progress(self, mock_snapshot: MagicMock) -> None:
        upstream = _snapshot(self.organization.id)
        worker = cast(dict[str, object], cast(list[object], upstream["workers"])[0])
        session = cast(dict[str, object], worker["session"])
        session["percentage"] = None
        mock_snapshot.return_value = Response(upstream, status=status.HTTP_200_OK)

        response = self.client.get(self._snapshot_url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["workers"][0]["session"]["percentage"] is None

    @patch("products.data_warehouse.backend.presentation.views.data_warehouse.managed_warehouse.monitoring_series_for")
    def test_timeseries_validates_and_forwards_the_allow_listed_query(self, mock_series: MagicMock) -> None:
        mock_series.return_value = Response(_series(self.organization.id), status=status.HTTP_200_OK)

        response = self.client.get(self._series_url())

        assert response.status_code == status.HTTP_200_OK
        mock_series.assert_called_once_with(str(self.organization.id), "query_rate", "6h")
        assert response.json()["series"][0]["labels"] == {"status": "success", "reason": "none"}

    @patch("products.data_warehouse.backend.presentation.views.data_warehouse.managed_warehouse.monitoring_series_for")
    def test_timeseries_rejects_invalid_query_before_calling_upstream(self, mock_series: MagicMock) -> None:
        response = self.client.get(self._series_url("metric=worker_states&window=2h"))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_series.assert_not_called()

    @patch("products.data_warehouse.backend.presentation.views.data_warehouse.managed_warehouse.monitoring_series_for")
    def test_timeseries_rejects_an_unexpected_upstream_label(self, mock_series: MagicMock) -> None:
        upstream = _series(self.organization.id)
        upstream_series = cast(list[object], upstream["series"])
        labels = cast(dict[str, str], cast(dict[str, object], upstream_series[0])["labels"])
        labels["pod"] = "sensitive-pod"
        mock_series.return_value = Response(upstream, status=status.HTTP_200_OK)

        response = self.client.get(self._series_url())

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "pod" not in response.content.decode()
        assert "sensitive-pod" not in response.content.decode()

    @parameterized.expand(
        [
            ("timeout", status.HTTP_504_GATEWAY_TIMEOUT, status.HTTP_504_GATEWAY_TIMEOUT),
            ("upstream_error", status.HTTP_503_SERVICE_UNAVAILABLE, status.HTTP_502_BAD_GATEWAY),
        ]
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.data_warehouse.managed_warehouse.monitoring_snapshot_for"
    )
    def test_snapshot_maps_upstream_failures_without_forwarding_details(
        self,
        _name: str,
        upstream_status: int,
        expected_status: int,
        mock_snapshot: MagicMock,
    ) -> None:
        mock_snapshot.return_value = Response(
            {"error": "private control-plane detail"},
            status=upstream_status,
        )

        response = self.client.get(self._snapshot_url())

        assert response.status_code == expected_status
        assert "private control-plane detail" not in response.content.decode()

    @parameterized.expand(
        [
            ("explicit_missing_warehouse", {"code": "managed_warehouse_not_found"}, status.HTTP_404_NOT_FOUND),
            ("old_control_plane_route", {"error": "404 page not found"}, status.HTTP_502_BAD_GATEWAY),
        ]
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.data_warehouse.managed_warehouse.monitoring_snapshot_for"
    )
    def test_snapshot_distinguishes_missing_warehouse_from_an_old_control_plane_route(
        self,
        _name: str,
        upstream_body: dict[str, str],
        expected_status: int,
        mock_snapshot: MagicMock,
    ) -> None:
        mock_snapshot.return_value = Response(upstream_body, status=status.HTTP_404_NOT_FOUND)

        response = self.client.get(self._snapshot_url())

        assert response.status_code == expected_status


@pytest.mark.ee
class TestManagedWarehouseMonitoringAccessControl(WarehouseAccessControlTestMixin):
    resource = "warehouse_objects"

    def setUp(self) -> None:
        super().setUp()
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="restricted_view",
            query={"kind": "HogQLQuery", "query": "select 1"},
            created_by=self.user,
        )
        self._create_project_default(access_level="none")
        self._create_access_control(
            self.viewer_user,
            resource="warehouse_view",
            resource_id=str(saved_query.id),
            access_level="viewer",
        )
        self.client.force_login(self.viewer_user)

    @parameterized.expand(
        [
            (
                "snapshot",
                "monitoring_snapshot_for",
                "managed-warehouse-monitoring/",
            ),
            (
                "timeseries",
                "monitoring_series_for",
                "managed-warehouse-monitoring-timeseries/?metric=query_rate&window=6h",
            ),
        ]
    )
    def test_org_wide_monitoring_requires_resource_level_warehouse_access(
        self,
        _name: str,
        upstream_method: str,
        endpoint: str,
    ) -> None:
        upstream_path = (
            f"products.data_warehouse.backend.presentation.views.data_warehouse.managed_warehouse.{upstream_method}"
        )
        with patch(upstream_path) as mock_upstream:
            upstream_body = (
                _snapshot(self.organization.id)
                if upstream_method == "monitoring_snapshot_for"
                else _series(self.organization.id)
            )
            mock_upstream.return_value = Response(
                upstream_body,
                status=status.HTTP_200_OK,
            )

            response = self.client.get(f"/api/projects/{self.team.id}/data_warehouse/{endpoint}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        mock_upstream.assert_not_called()


class TestManagedWarehouseMonitoringPersonalAPIKey(APIBaseTest):
    CONFIG_AUTO_LOGIN = False

    def _get_snapshot(self, token: str) -> Response:
        return self.client.get(
            f"/api/projects/{self.team.id}/data_warehouse/managed-warehouse-monitoring/",
            headers={"authorization": f"Bearer {token}"},
        )

    @patch(
        "products.data_warehouse.backend.presentation.views.data_warehouse.managed_warehouse.monitoring_snapshot_for"
    )
    def test_snapshot_requires_the_warehouse_view_read_scope(self, mock_snapshot: MagicMock) -> None:
        mock_snapshot.return_value = Response(_snapshot(self.organization.id), status=status.HTTP_200_OK)
        allowed_token = self.create_personal_api_key_with_scopes(["warehouse_view:read"])
        denied_token = self.create_personal_api_key_with_scopes(["query:read"])

        allowed_response = self._get_snapshot(allowed_token)
        denied_response = self._get_snapshot(denied_token)

        assert allowed_response.status_code == status.HTTP_200_OK
        assert denied_response.status_code == status.HTTP_403_FORBIDDEN
        assert mock_snapshot.call_count == 1
