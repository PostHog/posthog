from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.tasks.warehouse import infer_data_warehouse_saved_query_columns, validate_data_warehouse_table_columns

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.warehouse_sources.backend.models.table import DataWarehouseTable


class TestWarehouse(APIBaseTest):
    def test_infer_data_warehouse_saved_query_columns(self) -> None:
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="event_view",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "select event as event from events LIMIT 100"},
            columns={},
            status=DataWarehouseSavedQuery.Status.MODIFIED,
        )

        inferred = {"event": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "valid": True}}
        with (
            patch.object(DataWarehouseSavedQuery, "get_columns", return_value=inferred),
            patch.object(DataWarehouseSavedQuery, "s3_tables", new=[]),
        ):
            infer_data_warehouse_saved_query_columns(self.team.pk, str(saved_query.id))

        saved_query.refresh_from_db()
        assert saved_query.columns == inferred
        assert saved_query.external_tables == []

    def test_infer_data_warehouse_saved_query_columns_swallows_errors(self) -> None:
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="event_view",
            team=self.team,
            query={"kind": "HogQLQuery", "query": "select event as event from events LIMIT 100"},
            columns={},
            status=DataWarehouseSavedQuery.Status.MODIFIED,
        )

        with patch.object(DataWarehouseSavedQuery, "get_columns", side_effect=Exception("clickhouse unreachable")):
            # Must not raise — the edit that scheduled this task already succeeded.
            infer_data_warehouse_saved_query_columns(self.team.pk, str(saved_query.id))

        saved_query.refresh_from_db()
        assert saved_query.columns == {}

    def test_infer_data_warehouse_saved_query_columns_missing_query_noop(self) -> None:
        # A deleted/missing query id must not raise.
        infer_data_warehouse_saved_query_columns(self.team.pk, "00000000-0000-0000-0000-000000000000")

    @patch("posthog.tasks.warehouse.get_client")
    def test_validate_data_warehouse_table_columns(self, mock_get_client: MagicMock) -> None:
        mock_ph_client = MagicMock()
        mock_get_client.return_value = mock_ph_client

        table = DataWarehouseTable.objects.create(
            name="table_name",
            format="Parquet",
            team=self.team,
            columns={"some_columns": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)"}},
        )

        with patch.object(DataWarehouseTable, "validate_column_type", return_value=True):
            validate_data_warehouse_table_columns(self.team.pk, str(table.id))

        table.refresh_from_db()
        assert table.columns is not None
        some_columns = table.columns.get("some_columns")
        assert some_columns is not None
        valid = some_columns.get("valid")
        assert valid is True
