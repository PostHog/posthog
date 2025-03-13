from typing import Optional

from freezegun import freeze_time
from unittest.mock import patch

from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.web_analytics.revenue_example_external_tables import RevenueExampleExternalTablesQueryRunner
from posthog.schema import (
    RevenueExampleExternalTablesQuery,
    RevenueTrackingConfig,
    RevenueExampleExternalTablesQueryResponse,
    RevenueTrackingExternalDataSchema,
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

EMPTY_REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(events=[], externalDataSchemas=[])

SINGLE_TABLE_REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(
    events=[],
    externalDataSchemas=[
        RevenueTrackingExternalDataSchema(
            tableName="database_with_revenue_column",
            revenueColumn="revenue",
            timestampColumn="timestamp",
        )
    ],
)

MULTIPLE_TABLES_REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(
    events=[],
    externalDataSchemas=[
        RevenueTrackingExternalDataSchema(
            tableName="database_with_revenue_column_a",
            revenueColumn="revenue_a",
            timestampColumn="timestamp",
        ),
        RevenueTrackingExternalDataSchema(
            tableName="database_with_revenue_column_b",
            revenueColumn="revenue_b",
            timestampColumn="timestamp",
        ),
    ],
)


@snapshot_clickhouse_queries
class TestRevenueExampleExternalTablesQueryRunner(ClickhouseTestMixin, APIBaseTest):
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

    def _run_revenue_example_external_tables_query(
        self,
        revenue_tracking_config: RevenueTrackingConfig,
        limit_context: Optional[LimitContext] = None,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueExampleExternalTablesQuery(
                revenueTrackingConfig=revenue_tracking_config,
            )
            runner = RevenueExampleExternalTablesQueryRunner(team=self.team, query=query, limit_context=limit_context)
            response = runner.calculate()
            RevenueExampleExternalTablesQueryResponse.model_validate(response)
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
                ("database_with_revenue_column", 42),
                ("database_with_revenue_column", 43),
                ("database_with_revenue_column", 44),
            ],
            (
                "String",
                "Float64",
            ),
        ),
    )
    def test_single_table_query(self, mock_get_result):
        results = self._run_revenue_example_external_tables_query(SINGLE_TABLE_REVENUE_TRACKING_CONFIG).results

        assert len(results) == 3

        # table_name, revenue
        assert results[0] == ("database_with_revenue_column", 42)
        assert results[1] == ("database_with_revenue_column", 43)
        assert results[2] == ("database_with_revenue_column", 44)

    # NOTE: This test works just fine if you run it in isolation,
    # but it will crash if you run it with other tests because Clickhouse
    # runs UNION ALL queries in parallel, and we can't have that in tests
    # because it'll raise the following error:
    # clickhouse_driver.errors.PartiallyConsumedQueryError: Simultaneous queries on single connection detected
    #
    # Let's skip it for now until we figure out how to fix it
    #
    # @patch(
    #     "clickhouse_driver.result.QueryResult.get_result",
    #     return_value=(
    #         [
    #             ("database_with_revenue_column_a", 42),
    #             ("database_with_revenue_column_a", 43),
    #             ("database_with_revenue_column_a", 44),
    #             ("database_with_revenue_column_b", 43),
    #             ("database_with_revenue_column_b", 44),
    #             ("database_with_revenue_column_b", 45),
    #         ],
    #         (
    #             "String",
    #             "Float64",
    #         ),
    #     ),
    # )
    # def test_multiple_tables_query(self, mock_get_result):
    #     results = self._run_revenue_example_external_tables_query(MULTIPLE_TABLES_REVENUE_TRACKING_CONFIG).results

    #     assert len(results) == 6

    #     # Results are returned in the order defined by the SQL UNION ALL query
    #     # The first table from externalDataSchemas should come first
    #     assert results[0] == ("database_with_revenue_column_a", 42)
    #     assert results[1] == ("database_with_revenue_column_a", 43)
    #     assert results[2] == ("database_with_revenue_column_a", 44)
    #     assert results[3] == ("database_with_revenue_column_b", 43)
    #     assert results[4] == ("database_with_revenue_column_b", 44)
    #     assert results[5] == ("database_with_revenue_column_b", 45)
