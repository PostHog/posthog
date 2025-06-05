from unittest.mock import patch
from parameterized import parameterized
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_DAILY_SQL,
    WEB_BOUNCES_DAILY_SQL,
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
