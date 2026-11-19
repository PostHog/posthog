import json
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.response import Response

_VIEWS = "products.data_warehouse.backend.presentation.views.data_warehouse"


def _trino_snapshot(organization_id: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "org_id": str(organization_id),
        "as_of": "2026-09-30T17:00:00Z",
        "trino": {"state": "ready", "ready_at": "2026-09-01T12:00:00Z", "failed_at": None},
        "available": True,
        "limits": {"max_running_queries": 10, "max_queued_queries": 50},
        "totals": {
            "in_flight": 2,
            "running": 1,
            "queued": 1,
            "blocked": 0,
            "longest_running_ms": 9000,
            "physical_input_bytes": 150,
        },
        "queries": [
            {
                "query_id": "20260930_170000_00001_abcde",
                "state": "running",
                "user": "analyst",
                "source": "dbt",
                "query": "SELECT * FROM t WHERE email = ?",
                "created_at": "2026-09-30T16:59:51Z",
                "elapsed_ms": 9000,
                "queued_ms": 20,
                "cpu_ms": 900,
                "physical_input_bytes": 150,
                "peak_memory_bytes": 64,
                "processed_input_rows": 7,
                "progress_percentage": 50.0,
                "blocked": False,
            }
        ],
        "queries_truncated": False,
    }


def _trino_series(organization_id: object, metric: str = "queries_in_flight") -> dict[str, object]:
    return {
        "schema_version": 1,
        "org_id": str(organization_id),
        "metric": metric,
        "unit": "queries",
        "start": "2026-09-29T17:00:00Z",
        "end": "2026-09-30T17:00:00Z",
        "step_seconds": 60,
        "series": [{"labels": {"state": "running"}, "points": [{"timestamp": "2026-09-30T16:59:00Z", "value": 3}]}],
    }


class TestManagedWarehouseTrinoMonitoringAPI(APIBaseTest):
    def _snapshot_url(self) -> str:
        return f"/api/projects/{self.team.id}/data_warehouse/managed-warehouse-trino-monitoring/"

    def _series_url(self, query: str = "metric=queries_in_flight&window=6h") -> str:
        return f"/api/projects/{self.team.id}/data_warehouse/managed-warehouse-trino-monitoring-timeseries/?{query}"

    @patch(f"{_VIEWS}.managed_warehouse.trino_monitoring_snapshot_for")
    def test_snapshot_derives_the_organization_and_removes_unknown_fields(self, mock_snapshot: MagicMock) -> None:
        upstream = _trino_snapshot(self.organization.id)
        upstream["cell"] = {"id": "sensitive-cell"}
        cast(dict[str, object], upstream["trino"])["status_message"] = "sensitive reconcile detail"
        query = cast(dict[str, object], cast(list[object], upstream["queries"])[0])
        query["principal"] = "sensitive-principal"
        query["resource_group"] = "root.tenants.growth.sensitive"
        mock_snapshot.return_value = Response(upstream, status=status.HTTP_200_OK)

        response = self.client.get(self._snapshot_url())

        assert response.status_code == status.HTTP_200_OK
        mock_snapshot.assert_called_once_with(str(self.organization.id))
        body = response.json()
        assert set(body) == {
            "schema_version",
            "org_id",
            "as_of",
            "trino",
            "available",
            "limits",
            "totals",
            "queries",
            "queries_truncated",
        }
        assert body["queries"][0]["query"] == "SELECT * FROM t WHERE email = ?"
        serialized = json.dumps(body)
        for forbidden in ("sensitive", "principal", "resource_group", "status_message", "cell"):
            assert forbidden not in serialized

    @patch(f"{_VIEWS}.managed_warehouse.trino_monitoring_snapshot_for")
    def test_snapshot_accepts_a_query_without_a_start_time_or_progress(self, mock_snapshot: MagicMock) -> None:
        upstream = _trino_snapshot(self.organization.id)
        query = cast(dict[str, object], cast(list[object], upstream["queries"])[0])
        query["created_at"] = None
        query["progress_percentage"] = None
        query["user"] = ""
        query["source"] = ""
        mock_snapshot.return_value = Response(upstream, status=status.HTTP_200_OK)

        response = self.client.get(self._snapshot_url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["queries"][0]["created_at"] is None

    @patch(f"{_VIEWS}.managed_warehouse.trino_monitoring_snapshot_for")
    def test_snapshot_rejects_an_upstream_organization_mismatch(self, mock_snapshot: MagicMock) -> None:
        mock_snapshot.return_value = Response(_trino_snapshot("different-organization"), status=status.HTTP_200_OK)

        response = self.client.get(self._snapshot_url())

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "different-organization" not in response.content.decode()

    @parameterized.expand([("snapshot",), ("series",)])
    def test_trino_monitoring_returns_404_for_a_duckdb_organization(self, endpoint: str) -> None:
        url = self._snapshot_url() if endpoint == "snapshot" else self._series_url()
        with (
            patch(f"{_VIEWS}.managed_warehouse.data_ops_variant", return_value="duckdb"),
            patch(f"{_VIEWS}.managed_warehouse.trino_monitoring_snapshot_for") as mock_snapshot,
            patch(f"{_VIEWS}.managed_warehouse.trino_monitoring_series_for") as mock_series,
        ):
            response = self.client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "managed-warehouse-monitoring" in response.json()["error"]
        mock_snapshot.assert_not_called()
        mock_series.assert_not_called()

    @patch(f"{_VIEWS}.managed_warehouse.trino_monitoring_series_for")
    def test_timeseries_validates_and_forwards_the_allow_listed_query(self, mock_series: MagicMock) -> None:
        mock_series.return_value = Response(_trino_series(self.organization.id), status=status.HTTP_200_OK)

        response = self.client.get(self._series_url())

        assert response.status_code == status.HTTP_200_OK
        mock_series.assert_called_once_with(str(self.organization.id), "queries_in_flight", "6h")
        assert response.json()["series"][0]["labels"] == {"state": "running"}

    @parameterized.expand(
        [
            ("duckdb_only_metric", "metric=sessions_active&window=1h"),
            ("worker_metric", "metric=acquire_p95&window=1h"),
            ("unknown_window", "metric=query_rate&window=2h"),
        ]
    )
    @patch(f"{_VIEWS}.managed_warehouse.trino_monitoring_series_for")
    def test_timeseries_rejects_invalid_query_before_calling_upstream(
        self, _name: str, query: str, mock_series: MagicMock
    ) -> None:
        response = self.client.get(self._series_url(query))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_series.assert_not_called()

    @patch(f"{_VIEWS}.managed_warehouse.trino_monitoring_series_for")
    def test_timeseries_rejects_an_unexpected_upstream_label(self, mock_series: MagicMock) -> None:
        upstream = _trino_series(self.organization.id)
        cast(list[dict[str, object]], upstream["series"])[0]["labels"] = {"state": "running", "pod": "private-pod"}
        mock_series.return_value = Response(upstream, status=status.HTTP_200_OK)

        response = self.client.get(self._series_url())

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert "private-pod" not in response.content.decode()
