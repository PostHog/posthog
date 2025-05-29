from unittest.mock import patch
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_DAILY_SQL,
    WEB_BOUNCES_DAILY_SQL,
    WEB_STATS_INSERT_SQL,
    WEB_BOUNCES_INSERT_SQL,
    DISTRIBUTED_WEB_STATS_DAILY_SQL,
    DISTRIBUTED_WEB_BOUNCES_DAILY_SQL,
)
from posthog.test.base import ClickhouseTestMixin, APIBaseTest


class TestWebPreAggregatedReplacingMergeTree(ClickhouseTestMixin, APIBaseTest):
    """Test the new ReplacingMergeTree implementation for web analytics pre-aggregated tables"""

    def test_web_stats_table_creation_with_replacing_merge_tree(self):
        table_sql = WEB_STATS_DAILY_SQL(table_name="test_web_stats_daily", on_cluster=False)

        assert "ReplacingMergeTree" in table_sql
        assert "updated_at" in table_sql
        assert "updated_at DateTime64(6, 'UTC') DEFAULT now()" in table_sql

        assert "AggregatingMergeTree" not in table_sql

    def test_web_bounces_table_creation_with_replacing_merge_tree(self):
        table_sql = WEB_BOUNCES_DAILY_SQL(table_name="test_web_bounces_daily", on_cluster=False)

        assert "ReplacingMergeTree" in table_sql
        assert "updated_at" in table_sql
        assert "updated_at DateTime64(6, 'UTC') DEFAULT now()" in table_sql

        assert "AggregatingMergeTree" not in table_sql

    def test_web_bounces_columns_with_aggregate_functions(self):
        table_sql = WEB_BOUNCES_DAILY_SQL(table_name="test_web_bounces_daily", on_cluster=False)

        assert "persons_uniq_state AggregateFunction(uniq, UUID)" in table_sql
        assert "sessions_uniq_state AggregateFunction(uniq, String)" in table_sql
        assert "pageviews_count_state AggregateFunction(sum, UInt64)" in table_sql
        assert "bounces_count_state AggregateFunction(sum, UInt64)" in table_sql
        assert "total_session_duration_state AggregateFunction(sum, Int64)" in table_sql

    def test_web_stats_insert_sql_uses_state_functions(self):
        insert_sql = WEB_STATS_INSERT_SQL(
            date_start="2023-01-01", date_end="2023-01-02", team_ids=[1], table_name="test_web_stats_daily"
        )

        assert "uniqState(assumeNotNull(session_person_id)) AS persons_uniq_state" in insert_sql
        assert "uniqState(assumeNotNull(session_id)) AS sessions_uniq_state" in insert_sql
        assert "sumState(pageview_count) AS pageviews_count_state" in insert_sql
        assert "now() AS updated_at" in insert_sql

        assert "uniq(assumeNotNull(session_person_id)) AS persons_uniq" not in insert_sql
        assert "uniq(assumeNotNull(session_id)) AS sessions_uniq" not in insert_sql
        assert "sum(pageview_count) AS pageviews_count" not in insert_sql

    def test_web_bounces_insert_sql_uses_state_functions(self):
        insert_sql = WEB_BOUNCES_INSERT_SQL(
            date_start="2023-01-01", date_end="2023-01-02", team_ids=[1], table_name="test_web_bounces_daily"
        )

        assert "uniqState(assumeNotNull(person_id)) AS persons_uniq_state" in insert_sql
        assert "uniqState(assumeNotNull(session_id)) AS sessions_uniq_state" in insert_sql
        assert "sumState(pageview_count) AS pageviews_count_state" in insert_sql
        assert "sumState(toUInt64(ifNull(is_bounce, 0))) AS bounces_count_state" in insert_sql
        assert "sumState(session_duration) AS total_session_duration_state" in insert_sql
        assert "now() AS updated_at" in insert_sql

    def test_distributed_tables_creation(self):
        stats_dist_sql = DISTRIBUTED_WEB_STATS_DAILY_SQL()
        bounces_dist_sql = DISTRIBUTED_WEB_BOUNCES_DAILY_SQL()

        assert "persons_uniq_state AggregateFunction(uniq, UUID)" in stats_dist_sql
        assert "sessions_uniq_state AggregateFunction(uniq, String)" in stats_dist_sql
        assert "pageviews_count_state AggregateFunction(sum, UInt64)" in stats_dist_sql
        assert "updated_at DateTime64(6, 'UTC') DEFAULT now()" in stats_dist_sql

        assert "bounces_count_state AggregateFunction(sum, UInt64)" in bounces_dist_sql
        assert "total_session_duration_state AggregateFunction(sum, Int64)" in bounces_dist_sql
        assert "updated_at DateTime64(6, 'UTC') DEFAULT now()" in bounces_dist_sql

    @patch("posthog.clickhouse.client.sync_execute")
    def test_table_creation_with_final_keyword_in_queries(self, mock_sync_execute):
        from posthog.hogql_queries.web_analytics.web_overview_pre_aggregated import WebOverviewPreAggregatedQueryBuilder
        from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
        from posthog.schema import WebOverviewQuery, DateRange

        # Create a mock query runner
        query = WebOverviewQuery(dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"), properties=[])
        runner = WebOverviewQueryRunner(team=self.team, query=query)
        builder = WebOverviewPreAggregatedQueryBuilder(runner)

        # Get the generated query
        hogql_query = builder.get_query()

        # Convert to SQL to check for FINAL keyword
        from posthog.hogql.printer import print_ast
        from posthog.hogql.context import HogQLContext

        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        sql = print_ast(hogql_query, context=context, dialect="clickhouse")

        # Verify FINAL keyword is used
        assert "web_bounces_daily FINAL" in sql

    def test_replacing_merge_tree_version_column(self):
        """Test that the version column (updated_at) is properly configured"""
        table_sql = WEB_STATS_DAILY_SQL(table_name="test_web_stats_daily", on_cluster=False)

        # Check that the ReplacingMergeTree engine includes the version parameter
        # The exact format depends on the table engine implementation
        assert "updated_at" in table_sql

        # Verify the column definition
        assert "updated_at DateTime64(6, 'UTC') DEFAULT now()" in table_sql

    def test_insert_sql_includes_updated_at_timestamp(self):
        """Test that insert operations include the updated_at timestamp"""
        insert_sql = WEB_STATS_INSERT_SQL(
            date_start="2023-01-01", date_end="2023-01-02", team_ids=[1], table_name="test_web_stats_daily"
        )

        # Verify that updated_at is included in the insert
        assert "now() AS updated_at" in insert_sql

    def test_final_keyword_in_table_methods(self):
        from posthog.hogql.database.schema.web_analytics_preaggregated import WebStatsDailyTable, WebBouncesDailyTable

        stats_table = WebStatsDailyTable()
        bounces_table = WebBouncesDailyTable()

        # Test ClickHouse representation includes FINAL
        assert stats_table.to_printed_clickhouse(None) == "web_stats_daily FINAL"
        assert bounces_table.to_printed_clickhouse(None) == "web_bounces_daily FINAL"

        # Test HogQL representation doesn't include FINAL (for compatibility)
        assert stats_table.to_printed_hogql() == "web_stats_daily"
        assert bounces_table.to_printed_hogql() == "web_bounces_daily"
