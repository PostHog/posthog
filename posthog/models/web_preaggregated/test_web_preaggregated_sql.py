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
from posthog.hogql_queries.web_analytics.web_overview_pre_aggregated import WebOverviewPreAggregatedQueryBuilder
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.schema import WebOverviewQuery, DateRange
from posthog.hogql.printer import print_ast
from posthog.hogql.context import HogQLContext


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
        query = WebOverviewQuery(dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-31"), properties=[])
        runner = WebOverviewQueryRunner(team=self.team, query=query)
        builder = WebOverviewPreAggregatedQueryBuilder(runner)

        hogql_query = builder.get_query()

        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        sql = print_ast(hogql_query, context=context, dialect="clickhouse")

        assert "web_bounces_daily FINAL" in sql

    def test_replacing_merge_tree_version_column(self):
        table_sql = WEB_STATS_DAILY_SQL(table_name="test_web_stats_daily", on_cluster=False)

        assert "updated_at" in table_sql

        assert "updated_at DateTime64(6, 'UTC') DEFAULT now()" in table_sql

    def test_insert_sql_includes_updated_at_timestamp(self):
        insert_sql = WEB_STATS_INSERT_SQL(
            date_start="2023-01-01", date_end="2023-01-02", team_ids=[1], table_name="test_web_stats_daily"
        )

        assert "now() AS updated_at" in insert_sql
