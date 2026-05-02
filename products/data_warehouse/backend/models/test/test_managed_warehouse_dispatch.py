from __future__ import annotations

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from posthog.hogql.database.managed_warehouse_postgres_table import ManagedWarehousePostgresTable
from posthog.hogql.errors import QueryError

from products.data_warehouse.backend.models import DataWarehouseTable, ManagedWarehousePromotedTable

pytestmark = [pytest.mark.django_db]


class _FakeDuckgresServer:
    host = "duckgres.example.com"
    port = 5432
    database = "ducklake"
    username = "warehouse_user"
    password = "s3cret"


class TestHogqlDefinitionDispatch(BaseTest):
    def _make_promoted_table(
        self, schema: str = "public", table_name: str = "users"
    ) -> tuple[ManagedWarehousePromotedTable, DataWarehouseTable]:
        promoted = ManagedWarehousePromotedTable.objects.create(
            team=self.team, source_schema_name=schema, source_table_name=table_name
        )
        dw_table = DataWarehouseTable.objects.create(
            team=self.team,
            name=f"managed_warehouse.{schema}.{table_name}",
            format=DataWarehouseTable.TableFormat.ManagedWarehouse,
            url_pattern="",
            columns={"id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField", "valid": True}},
            managed_warehouse_promoted_table=promoted,
        )
        return promoted, dw_table

    @mock.patch("posthog.ducklake.common.get_duckgres_server_for_organization")
    @mock.patch("posthog.ducklake.common._get_org_id_for_team")
    def test_dispatches_to_managed_warehouse_postgres_table_when_format_set(self, mock_org_id, mock_get_server):
        mock_org_id.return_value = "org-123"
        mock_get_server.return_value = _FakeDuckgresServer()

        _, dw_table = self._make_promoted_table()
        result = dw_table.hogql_definition()

        assert isinstance(result, ManagedWarehousePostgresTable)
        assert result.host == "duckgres.example.com"
        assert result.port == 5432
        assert result.database == "ducklake"
        assert result.user == "warehouse_user"
        assert result.password == "s3cret"
        assert result.schema == "public"
        assert result.postgres_table_name == "users"

    @mock.patch("posthog.ducklake.common.get_duckgres_server_for_organization")
    @mock.patch("posthog.ducklake.common._get_org_id_for_team")
    def test_raises_query_error_when_no_duckgres_server_configured(self, mock_org_id, mock_get_server):
        mock_org_id.return_value = "org-123"
        mock_get_server.return_value = None

        _, dw_table = self._make_promoted_table()
        with pytest.raises(QueryError, match="No DuckgresServer configured"):
            dw_table.hogql_definition()

    @mock.patch("posthog.ducklake.common.get_duckgres_server_for_organization")
    @mock.patch("posthog.ducklake.common._get_org_id_for_team")
    def test_raises_query_error_when_org_lookup_fails(self, mock_org_id, mock_get_server):
        mock_org_id.side_effect = RuntimeError("no org")
        mock_get_server.return_value = _FakeDuckgresServer()

        _, dw_table = self._make_promoted_table()
        with pytest.raises(QueryError, match="Failed to resolve managed warehouse server"):
            dw_table.hogql_definition()

    def test_does_not_dispatch_when_format_is_not_managed_warehouse(self):
        # A normal Parquet warehouse table should not route through the managed-warehouse branch.
        dw_table = DataWarehouseTable.objects.create(
            team=self.team,
            name="some_csv_table",
            format=DataWarehouseTable.TableFormat.CSV,
            url_pattern="s3://bucket/path/*.csv",
            columns={},
        )
        result = dw_table.hogql_definition()
        assert not isinstance(result, ManagedWarehousePostgresTable)
