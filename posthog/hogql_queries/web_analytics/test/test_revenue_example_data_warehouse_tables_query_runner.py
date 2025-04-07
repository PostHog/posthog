from typing import Optional
import os

import pytest
from freezegun import freeze_time
from unittest.mock import patch

from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.web_analytics.revenue_example_data_warehouse_tables_query_runner import (
    RevenueExampleDataWarehouseTablesQueryRunner,
)
from posthog.schema import (
    RevenueExampleDataWarehouseTablesQuery,
    RevenueTrackingConfig,
    RevenueCurrencyPropertyConfig,
    RevenueExampleDataWarehouseTablesQueryResponse,
    RevenueTrackingDataWarehouseTable,
    CurrencyCode,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
)
from posthog.warehouse.models import (
    DataWarehouseTable,
    DataWarehouseCredential,
)

EMPTY_REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(baseCurrency=CurrencyCode.GBP, events=[], dataWarehouseTables=[])

SINGLE_TABLE_REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(
    baseCurrency=CurrencyCode.GBP,
    events=[],
    dataWarehouseTables=[
        RevenueTrackingDataWarehouseTable(
            tableName="database_with_revenue_column",
            distinctIdColumn="id",
            revenueColumn="revenue",
            timestampColumn="timestamp",
        )
    ],
)

MULTIPLE_TABLES_REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(
    baseCurrency=CurrencyCode.GBP,
    events=[],
    dataWarehouseTables=[
        RevenueTrackingDataWarehouseTable(
            tableName="database_with_revenue_column_a",
            distinctIdColumn="id",
            revenueColumn="revenue_a",
            timestampColumn="timestamp",
        ),
        RevenueTrackingDataWarehouseTable(
            tableName="database_with_revenue_column_b",
            distinctIdColumn="id",
            revenueColumn="revenue_b",
            timestampColumn="timestamp",
            revenueCurrencyColumn=RevenueCurrencyPropertyConfig(static=CurrencyCode.EUR),
        ),
        RevenueTrackingDataWarehouseTable(
            tableName="database_with_revenue_column_c",
            distinctIdColumn="id",
            revenueColumn="revenue_c",
            timestampColumn="timestamp",
            revenueCurrencyColumn=RevenueCurrencyPropertyConfig(property="currency"),
        ),
    ],
)


# NOTE: This test works just fine if you run it in isolation,
# but it will crash if you run it with other tests because Clickhouse
# runs UNION ALL queries in parallel, and we can't have that in tests
# because it'll raise the following error:
# clickhouse_driver.errors.PartiallyConsumedQueryError: Simultaneous queries on single connection detected
#
# Let's skip it for now until we figure out how to fix it
@pytest.mark.skipif("CI" in os.environ, reason="Test skipped in CI environment")
@snapshot_clickhouse_queries
class TestRevenueExampleDataWarehouseTablesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-29"

    def setUp(self):
        super().setUp()

        # Register tables in Django DB for proper HogQL access
        self._register_warehouse_tables()

    def _register_warehouse_tables(self):
        # Create credential for each table (required by the model)
        self.credential = DataWarehouseCredential.objects.create(
            team=self.team,
            access_key="test-key",
            access_secret="test-secret",
        )

        # Register tables in Django - this doesn't create anything in Clickhouse
        # It just registers the schema for HogQL to use
        self.tables = []

        # First table
        table_1 = DataWarehouseTable.objects.create(
            name="database_with_revenue_column",
            format=DataWarehouseTable.TableFormat.Parquet,  # Parquet is commonly used in other tests
            team=self.team,
            credential=self.credential,
            url_pattern="test://localhost",  # Doesn't matter for tests
            columns={
                "id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                "revenue": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                "timestamp": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime", "schema_valid": True},
            },
        )
        self.tables.append(table_1)

        # Second table
        table_2 = DataWarehouseTable.objects.create(
            name="database_with_revenue_column_a",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=self.credential,
            url_pattern="test://localhost",  # Doesn't matter for tests
            columns={
                "id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                "revenue_a": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                "timestamp": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime", "schema_valid": True},
            },
        )
        self.tables.append(table_2)

        # Third table
        table_3 = DataWarehouseTable.objects.create(
            name="database_with_revenue_column_b",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=self.credential,
            url_pattern="test://localhost",  # Doesn't matter for tests
            columns={
                "id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                "revenue_b": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                "timestamp": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime", "schema_valid": True},
            },
        )
        self.tables.append(table_3)

        # Fourth table
        table_4 = DataWarehouseTable.objects.create(
            name="database_with_revenue_column_c",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=self.credential,
            url_pattern="test://localhost",  # Doesn't matter for tests
            columns={
                "id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                "revenue_c": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                "currency": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                "timestamp": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime", "schema_valid": True},
            },
        )
        self.tables.append(table_4)

    def _run_revenue_example_external_tables_query(
        self,
        revenue_tracking_config: RevenueTrackingConfig,
        limit_context: Optional[LimitContext] = None,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueExampleDataWarehouseTablesQuery(
                revenueTrackingConfig=revenue_tracking_config,
            )
            runner = RevenueExampleDataWarehouseTablesQueryRunner(
                team=self.team, query=query, limit_context=limit_context
            )
            response = runner.calculate()
            RevenueExampleDataWarehouseTablesQueryResponse.model_validate(response)
            return response

    def tearDown(self):
        # Clean up the Django database tables
        for table in self.tables:
            table.delete()
        self.credential.delete()
        super().tearDown()

    def test_no_crash_when_no_data(self):
        results = self._run_revenue_example_external_tables_query(EMPTY_REVENUE_TRACKING_CONFIG).results

        assert len(results) == 0

    @patch(
        "clickhouse_driver.result.QueryResult.get_result",
        return_value=(
            [
                ("database_with_revenue_column", "distinct_id_1", 42, "USD", 35, "GBP"),
                ("database_with_revenue_column", "distinct_id_2", 43, "USD", 36, "GBP"),
                ("database_with_revenue_column", "distinct_id_3", 44, "USD", 37, "GBP"),
            ],
            (
                "String",
                "String",
                "Float64",
                "String",
                "Float64",
                "String",
            ),
        ),
    )
    def test_single_table_query(self, mock_get_result):
        response = self._run_revenue_example_external_tables_query(SINGLE_TABLE_REVENUE_TRACKING_CONFIG)
        results = response.results

        # 3 rows, 6 columns
        assert len(results) == 3
        assert len(results[0]) == 6
        assert len(response.columns) == 6

        assert results[0] == ("database_with_revenue_column", "distinct_id_1", 42, "USD", 42, "GBP")
        assert results[1] == ("database_with_revenue_column", "distinct_id_2", 43, "USD", 43, "GBP")
        assert results[2] == ("database_with_revenue_column", "distinct_id_3", 44, "USD", 44, "GBP")

    @patch(
        "clickhouse_driver.result.QueryResult.get_result",
        return_value=(
            [
                ("database_with_revenue_column_a", "distinct_id_1", 42, "USD", 42, "GBP"),
                ("database_with_revenue_column_a", "distinct_id_2", 43, "USD", 43, "GBP"),
                ("database_with_revenue_column_a", "distinct_id_3", 44, "USD", 44, "GBP"),
                ("database_with_revenue_column_b", "distinct_id_1", 43, "USD", 43, "GBP"),
                ("database_with_revenue_column_b", "distinct_id_2", 44, "USD", 44, "GBP"),
                ("database_with_revenue_column_b", "distinct_id_3", 45, "USD", 45, "GBP"),
            ],
            (
                "String",
                "Float64",
                "String",
                "Float64",
                "String",
            ),
        ),
    )
    def test_multiple_tables_query(self, mock_get_result):
        response = self._run_revenue_example_external_tables_query(MULTIPLE_TABLES_REVENUE_TRACKING_CONFIG)
        results = response.results

        # 6 rows, 6 columns
        assert len(results) == 6
        assert len(results[0]) == 6
        assert len(response.columns) == 6

        # Results are returned in the order defined by the SQL UNION ALL query
        # The first table from dataWarehouseTables should come first
        assert results[0] == ("database_with_revenue_column_a", "distinct_id_1", 42, "USD", 42, "GBP")
        assert results[1] == ("database_with_revenue_column_a", "distinct_id_2", 43, "USD", 43, "GBP")
        assert results[2] == ("database_with_revenue_column_a", "distinct_id_3", 44, "USD", 44, "GBP")
        assert results[3] == ("database_with_revenue_column_b", "distinct_id_1", 43, "USD", 43, "GBP")
        assert results[4] == ("database_with_revenue_column_b", "distinct_id_2", 44, "USD", 44, "GBP")
        assert results[5] == ("database_with_revenue_column_b", "distinct_id_3", 45, "USD", 45, "GBP")
