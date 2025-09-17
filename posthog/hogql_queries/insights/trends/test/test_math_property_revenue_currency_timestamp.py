from pathlib import Path

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from posthog.schema import DataWarehouseNode, DateRange, PropertyMathType, TrendsQuery

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv

TEST_BUCKET = "test_storage_bucket-posthog.trends.datawarehouse.timestamp_handling"


@pytest.mark.django_db
class TestDataWarehouseTimestampHandling(ClickhouseTestMixin, BaseTest):
    def teardown_method(self, method) -> None:
        if hasattr(self, "cleanup_dw_table"):
            self.cleanup_dw_table()

    def setup_test_data_warehouse_table(self):
        # Create CSV data with mixed timestamp scenarios - including NULL timestamps
        csv_content = """id,timestamp_field,revenue_amount,currency_code
1,2023-01-01 10:00:00,100.50,USD
2,2023-01-02 11:30:00,75.25,EUR
3,,50.00,GBP
4,2023-01-04 14:15:00,200.75,JPY
5,,125.30,CAD"""

        # Write test CSV file
        csv_path = Path(__file__).parent / "data" / "timestamp_test.csv"
        csv_path.parent.mkdir(exist_ok=True)
        with open(csv_path, "w") as f:
            f.write(csv_content)

        # Create data warehouse table
        table, source, credential, df, cleanup_fn = create_data_warehouse_table_from_csv(
            csv_path=csv_path,
            table_name="timestamp_test_table",
            table_columns={
                "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "timestamp_field": {"clickhouse": "Nullable(DateTime64(3, 'UTC'))", "hogql": "DateTimeDatabaseField"},
                "revenue_amount": {"clickhouse": "Float64", "hogql": "FloatDatabaseField"},
                "currency_code": {"clickhouse": "String", "hogql": "StringDatabaseField"},
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )

        self.cleanup_dw_table = cleanup_fn

        # Clean up CSV file
        csv_path.unlink()

        return table.name

    def test_null_timestamps_currency_conversion(self):
        table_name = self.setup_test_data_warehouse_table()

        # Set up team with base currency for conversion
        self.team.base_currency = "USD"
        self.team.save()

        # Create trends query with currency conversion
        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-05"),
            series=[
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    timestamp_field="timestamp_field",
                    distinct_id_field="id",
                    id_field="id",
                    math=PropertyMathType.SUM,
                    math_property="revenue_amount",
                    math_property_revenue_currency={"property": "currency_code"},
                    dw_source_type="cloud",  # Uses coalesce logic
                )
            ],
        )

        runner = TrendsQueryRunner(query=trends_query, team=self.team)
        result = runner.calculate()

        assert result.results is not None
        assert len(result.results) > 0

    def test_self_managed_vs_cloud_sources(self):
        table_name = self.setup_test_data_warehouse_table()

        # Set up team with base currency for conversion
        self.team.base_currency = "USD"
        self.team.save()

        self_managed_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-05"),
            series=[
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    timestamp_field="timestamp_field",
                    distinct_id_field="id",
                    id_field="id",
                    math=PropertyMathType.SUM,
                    math_property="revenue_amount",
                    math_property_revenue_currency={"property": "currency_code"},
                    dw_source_type="self-managed",  # Uses today() to avoid string parsing issues
                )
            ],
        )

        cloud_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-05"),
            series=[
                DataWarehouseNode(
                    id=table_name,
                    table_name=table_name,
                    timestamp_field="timestamp_field",
                    distinct_id_field="id",
                    id_field="id",
                    math=PropertyMathType.SUM,
                    math_property="revenue_amount",
                    math_property_revenue_currency={"property": "currency_code"},
                    dw_source_type="cloud",  # Uses coalesce logic
                )
            ],
        )
        self_managed_runner = TrendsQueryRunner(query=self_managed_query, team=self.team)
        cloud_runner = TrendsQueryRunner(query=cloud_query, team=self.team)

        self_managed_result = self_managed_runner.calculate()
        cloud_result = cloud_runner.calculate()

        assert self_managed_result.results is not None
        assert cloud_result.results is not None

    @snapshot_clickhouse_queries
    def test_string_and_date32_fields(self):
        csv_content = """id,timestamp_str,revenue_amount,currency_code
1,2023-01-01,100.50,USD
2,2023-01-02,75.25,EUR
3,,50.00,GBP
4,2023-01-04,200.75,JPY
5,,125.30,CAD"""

        date32_csv_content = """id,timestamp_date32,revenue_amount,currency_code
1,2023-01-01,100.50,USD
2,2023-01-02,75.25,EUR
3,1970-01-01,50.00,GBP
4,2023-01-04,200.75,JPY
5,1970-01-01,125.30,CAD"""

        string_csv_path = Path(__file__).parent / "data" / "string_timestamp_test.csv"
        string_csv_path.parent.mkdir(exist_ok=True)
        with open(string_csv_path, "w") as f:
            f.write(csv_content)

        string_table, _, _, _, string_cleanup = create_data_warehouse_table_from_csv(
            csv_path=string_csv_path,
            table_name="string_timestamp_table",
            table_columns={
                "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "timestamp_str": {"clickhouse": "Nullable(String)", "hogql": "StringDatabaseField"},
                "revenue_amount": {"clickhouse": "Float64", "hogql": "FloatDatabaseField"},
                "currency_code": {"clickhouse": "String", "hogql": "StringDatabaseField"},
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )

        date32_csv_path = Path(__file__).parent / "data" / "date32_timestamp_test.csv"
        with open(date32_csv_path, "w") as f:
            f.write(date32_csv_content)

        date32_table, _, _, _, date32_cleanup = create_data_warehouse_table_from_csv(
            csv_path=date32_csv_path,
            table_name="date32_timestamp_table",
            table_columns={
                "id": {"clickhouse": "String", "hogql": "StringDatabaseField"},
                "timestamp_date32": {"clickhouse": "Date32", "hogql": "DateDatabaseField"},
                "revenue_amount": {"clickhouse": "Float64", "hogql": "FloatDatabaseField"},
                "currency_code": {"clickhouse": "String", "hogql": "StringDatabaseField"},
            },
            test_bucket=TEST_BUCKET,
            team=self.team,
        )

        self.team.base_currency = "USD"
        self.team.save()

        try:
            string_query = TrendsQuery(
                kind="TrendsQuery",
                dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-05"),
                series=[
                    DataWarehouseNode(
                        id=string_table.name,
                        table_name=string_table.name,
                        timestamp_field="timestamp_str",
                        distinct_id_field="id",
                        id_field="id",
                        math=PropertyMathType.SUM,
                        math_property="revenue_amount",
                        math_property_revenue_currency={"property": "currency_code"},
                        dw_source_type="cloud",
                    )
                ],
            )

            date32_query = TrendsQuery(
                kind="TrendsQuery",
                dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-05"),
                series=[
                    DataWarehouseNode(
                        id=date32_table.name,
                        table_name=date32_table.name,
                        timestamp_field="timestamp_date32",
                        distinct_id_field="id",
                        id_field="id",
                        math=PropertyMathType.SUM,
                        math_property="revenue_amount",
                        math_property_revenue_currency={"property": "currency_code"},
                        dw_source_type="cloud",
                    )
                ],
            )

            string_runner = TrendsQueryRunner(query=string_query, team=self.team)
            date32_runner = TrendsQueryRunner(query=date32_query, team=self.team)

            string_result = string_runner.calculate()
            date32_result = date32_runner.calculate()

            assert string_result.results is not None
            assert len(string_result.results) > 0
            assert date32_result.results is not None
            assert len(date32_result.results) > 0

            string_revenue = string_result.results[0]["count"]
            date32_revenue = date32_result.results[0]["count"]

            assert string_revenue > 0
            assert date32_revenue > 0

        finally:
            string_cleanup()
            date32_cleanup()
            string_csv_path.unlink()
            date32_csv_path.unlink()
