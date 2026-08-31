from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.hogql.query import HogQLQueryExecutor

from products.data_warehouse.backend.direct_trino import DIRECT_TRINO_URL_PATTERN, get_direct_trino_table_options
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestDirectTrinoQuery(APIBaseTest):
    def _create_source_and_table(self) -> ExternalDataSource:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.TRINO,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="analytics",
            job_inputs={
                "host": "trino.example.com",
                "port": 443,
                "catalog": "ducklake",
                "schema": "analytics",
                "auth_type": {"selection": "none", "user": "posthog"},
                "use_ssl": True,
                "verify_ssl": True,
            },
        )
        DataWarehouseTable.objects.create(
            name="orders",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            external_data_source=source,
            url_pattern=DIRECT_TRINO_URL_PATTERN,
            columns={
                "id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True},
                "status": {"hogql": "StringDatabaseField", "clickhouse": "String", "valid": True},
            },
            options=get_direct_trino_table_options(
                source_catalog="ducklake",
                source_schema="analytics",
                source_table_name="materialized_orders",
            ),
        )
        return source

    def test_query_editor_compiles_to_explicit_trino_relation(self) -> None:
        source = self._create_source_and_table()
        executor = HogQLQueryExecutor(
            query="SELECT ID FROM ORDERS WHERE STATUS = 'paid'",
            team=self.team,
            connection_id=str(source.id),
        )

        sql, context = executor.generate_clickhouse_sql()

        self.assertIn('"ducklake"."analytics"."materialized_orders"', sql)
        self.assertEqual(executor.direct_dialect, "trino")
        self.assertEqual(executor.direct_values, context.values)
        self.assertIn("paid", context.values.values())

    @patch("posthog.hogql.direct_sql.trino_adapter.TrinoAdapter.validate_source_config")
    @patch("products.warehouse_sources.backend.facade.source_management.connect_trino")
    def test_query_editor_executes_compiled_values_as_driver_parameters(
        self, mock_connect_trino: MagicMock, mock_validate_source_config: MagicMock
    ) -> None:
        source = self._create_source_and_table()
        mock_validate_source_config.return_value = (MagicMock(), MagicMock())
        cursor = MagicMock()
        cursor.fetchmany.return_value = [(7,)]
        cursor.description = [("id", "bigint")]
        connection = MagicMock()
        connection.cursor.return_value = cursor
        mock_connect_trino.return_value.__enter__.return_value = connection
        executor = HogQLQueryExecutor(
            query="SELECT id FROM orders WHERE status = 'paid' LIMIT 1",
            team=self.team,
            connection_id=str(source.id),
        )

        response = executor.execute()

        submitted_sql, submitted_values = cursor.execute.call_args.args
        self.assertIn('"ducklake"."analytics"."materialized_orders"', submitted_sql)
        self.assertIn("?", submitted_sql)
        self.assertNotIn("paid", submitted_sql)
        self.assertEqual(submitted_values, ["paid"])
        self.assertEqual(response.results, [(7,)])
