from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.schema import HogQLQuery

from posthog.hogql.query import HogQLQueryExecutor
from posthog.hogql.transforms.trino.errors import TrinoLoweringError

from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

from products.data_warehouse.backend.facade.api import DIRECT_TRINO_URL_PATTERN
from products.data_warehouse.backend.facade.sources import (
    DIRECT_TRINO_CATALOG_OPTION,
    DIRECT_TRINO_SCHEMA_OPTION,
    DIRECT_TRINO_TABLE_OPTION,
)
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
            options={
                DIRECT_TRINO_CATALOG_OPTION: "ducklake",
                DIRECT_TRINO_SCHEMA_OPTION: "analytics",
                DIRECT_TRINO_TABLE_OPTION: "materialized_orders",
            },
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

    def test_query_editor_uses_pure_compilation(self) -> None:
        source = self._create_source_and_table()
        runner = HogQLQueryRunner(
            team=self.team,
            query=HogQLQuery(
                query="SELECT matchesAction(1) FROM orders",
                connectionId=str(source.id),
            ),
        )

        with self.assertRaises(TrinoLoweringError) as error:
            runner.calculate()

        self.assertEqual(error.exception.feature_code, "TRINO_PURE_ACTION_UNSUPPORTED")

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
        runner = HogQLQueryRunner(
            team=self.team,
            query=HogQLQuery(
                query="SELECT id FROM orders WHERE status = 'paid' LIMIT 1",
                connectionId=str(source.id),
            ),
        )

        response = runner.calculate()

        submitted_sql, submitted_values = cursor.execute.call_args.args
        self.assertIn('"ducklake"."analytics"."materialized_orders"', submitted_sql)
        self.assertIn("?", submitted_sql)
        self.assertNotIn("paid", submitted_sql)
        self.assertEqual(submitted_values, ["paid"])
        self.assertEqual(response.results, [(7,)])
