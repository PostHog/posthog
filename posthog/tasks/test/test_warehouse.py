from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.tasks.warehouse import validate_data_warehouse_table_columns

from products.data_warehouse.backend.models.table import DataWarehouseTable


class TestWarehouse(APIBaseTest):
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

        assert table.columns.get("some_columns").get("valid") is True
