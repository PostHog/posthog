import re
from unittest.mock import patch
from parameterized import parameterized
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_DAILY_SQL,
    WEB_BOUNCES_DAILY_SQL,
    WEB_ANALYTICS_DIMENSIONS,
    WEB_STATS_DIMENSIONS,
    WEB_BOUNCES_DIMENSIONS,
)
from posthog.test.base import ClickhouseTestMixin, APIBaseTest
from posthog.hogql_queries.web_analytics.web_overview_pre_aggregated import WebOverviewPreAggregatedQueryBuilder
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.schema import WebOverviewQuery, DateRange
from posthog.hogql.printer import print_ast
from posthog.hogql.context import HogQLContext


class TestWebPreAggregatedReplacingMergeTree(ClickhouseTestMixin, APIBaseTest):
    TEST_TABLE_STATS = "test_web_stats_daily"
    TEST_TABLE_BOUNCES = "test_web_bounces_daily"
    TEST_DATE_START = "2023-01-01"
    TEST_DATE_END = "2023-01-02"
    TEST_TEAM_IDS = [1]

    REPLACING_MERGE_TREE_PATTERNS = [
        "ReplacingMergeTree",
        "updated_at DateTime64(6, 'UTC') DEFAULT now()",
    ]

    AGGREGATE_FUNCTION_PATTERNS = {
        "persons_uniq_state": "AggregateFunction(uniq, UUID)",
        "sessions_uniq_state": "AggregateFunction(uniq, String)",
        "pageviews_count_state": "AggregateFunction(sum, UInt64)",
        "bounces_count_state": "AggregateFunction(sum, UInt64)",
        "total_session_duration_state": "AggregateFunction(sum, Int64)",
        "total_session_count_state": "AggregateFunction(sum, UInt64)",
    }

    def _assert_sql_contains_patterns(self, sql: str, patterns: list[str], should_contain: bool = True):
        for pattern in patterns:
            if should_contain:
                assert pattern in sql, f"Expected '{pattern}' in SQL"
            else:
                assert pattern not in sql, f"Did not expect '{pattern}' in SQL"

    def _assert_sql_contains_aggregate_functions(self, sql: str, function_names: list[str]):
        for func_name in function_names:
            expected_pattern = f"{func_name} {self.AGGREGATE_FUNCTION_PATTERNS[func_name]}"
            assert expected_pattern in sql, f"Expected aggregate function '{expected_pattern}' in SQL"

    def _get_web_stats_sql(self, table_name: str | None = None) -> str:
        return WEB_STATS_DAILY_SQL(table_name=table_name or self.TEST_TABLE_STATS, on_cluster=False)

    def _get_web_bounces_sql(self, table_name: str | None = None) -> str:
        return WEB_BOUNCES_DAILY_SQL(table_name=table_name or self.TEST_TABLE_BOUNCES, on_cluster=False)

    def _extract_columns_from_sql(self, sql: str) -> list[str]:
        # Find the columns section between ( and ) ENGINE =
        pattern = r"\(\s*(.*?)\s*\)\s*ENGINE\s*="
        match = re.search(pattern, sql, re.DOTALL)
        if not match:
            return []

        columns_text = match.group(1)
        lines = [line.strip().rstrip(",") for line in columns_text.split("\n") if line.strip()]

        # Filter out updated_at and aggregate functions only
        columns_to_ignore = {"updated_at"}
        aggregate_suffixes = {"_uniq_state", "_count_state", "_duration_state"}

        dimension_columns = []
        for line in lines:
            if not line:
                continue
            # Extract column name (first word)
            col_name = line.split()[0]
            # Skip updated_at and aggregate functions
            if col_name not in columns_to_ignore and not any(
                col_name.endswith(suffix) for suffix in aggregate_suffixes
            ):
                dimension_columns.append(col_name)

        return dimension_columns

    def _extract_order_by_from_sql(self, sql: str) -> list[str]:
        pattern = r"ORDER\s+BY\s+\((.*?)\)"
        match = re.search(pattern, sql, re.DOTALL)
        if not match:
            return []

        order_by_text = match.group(1)
        columns = [col.strip() for col in order_by_text.split(",")]

        return columns

    def _get_expected_full_columns(self, dimensions: list[str]) -> set[str]:
        """Get the expected full column set including base columns and dimensions"""
        base_columns = {"period_bucket", "team_id", "host", "device_type"}
        return base_columns | set(dimensions)

    def _get_expected_order_by_columns(self, dimensions: list[str], bucket_column: str = "period_bucket") -> set[str]:
        """Get the expected ORDER BY columns including base columns and dimensions"""
        base_columns = {"team_id", bucket_column, "host", "device_type"}
        return base_columns | set(dimensions)

    @parameterized.expand(
        [
            ("web_stats", _get_web_stats_sql),
            ("web_bounces", _get_web_bounces_sql),
        ]
    )
    def test_table_creation_uses_replacing_merge_tree(self, table_type: str, sql_generator):
        table_sql = sql_generator(self)

        self._assert_sql_contains_patterns(table_sql, self.REPLACING_MERGE_TREE_PATTERNS)
        self._assert_sql_contains_patterns(table_sql, ["AggregatingMergeTree"], should_contain=False)

    def test_web_bounces_has_required_aggregate_functions(self):
        table_sql = self._get_web_bounces_sql()

        bounces_specific_functions = [
            "persons_uniq_state",
            "sessions_uniq_state",
            "pageviews_count_state",
            "bounces_count_state",
            "total_session_duration_state",
            "total_session_count_state",
        ]

        self._assert_sql_contains_aggregate_functions(table_sql, bounces_specific_functions)

    def test_dimensions_consistency(self):
        stats_sql = self._get_web_stats_sql()
        stats_columns = self._extract_columns_from_sql(stats_sql)
        stats_order_by = self._extract_order_by_from_sql(stats_sql)

        expected_stats_columns = self._get_expected_full_columns(WEB_STATS_DIMENSIONS)
        expected_stats_order_by = self._get_expected_order_by_columns(WEB_STATS_DIMENSIONS)

        assert set(stats_columns) == expected_stats_columns
        assert set(stats_order_by) == expected_stats_order_by

        bounces_sql = self._get_web_bounces_sql()
        bounces_columns = self._extract_columns_from_sql(bounces_sql)
        bounces_order_by = self._extract_order_by_from_sql(bounces_sql)

        expected_bounces_columns = self._get_expected_full_columns(WEB_BOUNCES_DIMENSIONS)
        expected_bounces_order_by = self._get_expected_order_by_columns(WEB_BOUNCES_DIMENSIONS)

        assert set(bounces_columns) == expected_bounces_columns
        assert set(bounces_order_by) == expected_bounces_order_by

    def test_dimension_structure_hierarchy(self):
        expected_web_stats = ["pathname", *WEB_ANALYTICS_DIMENSIONS]
        assert WEB_STATS_DIMENSIONS == expected_web_stats

        assert WEB_BOUNCES_DIMENSIONS == WEB_ANALYTICS_DIMENSIONS

        assert "referring_domain" in WEB_ANALYTICS_DIMENSIONS
        assert "end_pathname" in WEB_ANALYTICS_DIMENSIONS

        assert "pathname" in WEB_STATS_DIMENSIONS
        assert "pathname" not in WEB_BOUNCES_DIMENSIONS

    @patch("posthog.clickhouse.client.sync_execute")
    def test_queries_use_final_keyword(self, mock_sync_execute):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from=self.TEST_DATE_START, date_to="2023-01-31"), properties=[]
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query)
        builder = WebOverviewPreAggregatedQueryBuilder(runner)

        hogql_query = builder.get_query()
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        sql = print_ast(hogql_query, context=context, dialect="clickhouse")

        assert "web_bounces_combined FINAL" in sql

    def test_replacing_merge_tree_version_column(self):
        table_sql = WEB_STATS_DAILY_SQL(table_name="test_web_stats_daily", on_cluster=False)

        assert "updated_at" in table_sql

        assert "updated_at DateTime64(6, 'UTC') DEFAULT now()" in table_sql
