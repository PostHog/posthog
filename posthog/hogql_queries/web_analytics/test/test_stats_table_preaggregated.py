from unittest.mock import patch

import pytest
from posthog.hogql import ast
from posthog.hogql.printer import print_ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.test.utils import pretty_print_in_tests

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.stats_table_pre_aggregated import StatsTablePreAggregatedQueryBuilder
from posthog.models.utils import uuid7
from posthog.schema import (
    WebStatsTableQuery,
    DateRange,
    WebStatsBreakdown,
    WebAnalyticsOrderByFields,
    WebAnalyticsOrderByDirection,
    CompareFilter,
    EventPropertyFilter,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
)


class TestStatsTablePreAggregated(ClickhouseTestMixin, APIBaseTest):
    """
    Test suite for stats table pre-aggregated functionality that verifies
    state aggregations work correctly with the actual query runners.
    """

    snapshot: any

    def _create_events(self, data: list[dict]) -> None:
        """Helper method to create events in ClickHouse for testing."""
        for event in data:
            sync_execute(
                """
                INSERT INTO events (uuid, team_id, distinct_id, timestamp, event, properties, person_id)
                VALUES (%(uuid)s, %(team_id)s, %(distinct_id)s, %(timestamp)s, %(event)s, %(properties)s, %(person_id)s)
                """,
                {
                    "uuid": event.get("uuid", str(uuid7())),
                    "team_id": self.team.pk,
                    "distinct_id": event["distinct_id"],
                    "timestamp": event["timestamp"],
                    "event": event.get("event", "$pageview"),
                    "properties": event.get("properties", {}),
                    "person_id": event.get("person_id", str(uuid7())),
                },
            )

    @pytest.mark.django_db
    def test_can_use_preaggregated_tables_device_breakdown(self):
        """Test that we can use pre-aggregated tables for device breakdown."""
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-02"),
            breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
            properties=[],
            limit=10,
        )

        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        builder = StatsTablePreAggregatedQueryBuilder(runner)

        assert builder.can_use_preaggregated_tables() is True

    @pytest.mark.django_db
    def test_cannot_use_preaggregated_for_unsupported_breakdown(self):
        """Test that we cannot use pre-aggregated tables for unsupported breakdowns."""
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-02"),
            breakdownBy=WebStatsBreakdown.FRUSTRATION_METRICS,  # Not supported
            properties=[],
            limit=10,
        )

        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        builder = StatsTablePreAggregatedQueryBuilder(runner)

        assert builder.can_use_preaggregated_tables() is False

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_device_type_breakdown_query_generation(self):
        """Test query generation for device type breakdown with state aggregations."""
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-02"),
            breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
            properties=[],
            limit=10,
        )

        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        builder = StatsTablePreAggregatedQueryBuilder(runner)

        query_ast = builder.get_query()
        sql = self._print_select(query_ast)

        assert self.snapshot == sql

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_browser_breakdown_query_generation(self):
        """Test query generation for browser breakdown with state aggregations."""
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-02"),
            breakdownBy=WebStatsBreakdown.BROWSER,
            properties=[],
            orderBy=(WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.DESC),
            limit=5,
        )

        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        builder = StatsTablePreAggregatedQueryBuilder(runner)

        query_ast = builder.get_query()
        sql = self._print_select(query_ast)

        assert self.snapshot == sql

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_page_breakdown_with_bounce_rate_query_generation(self):
        """Test query generation for page breakdown with bounce rate calculations using state aggregations."""
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-02"),
            breakdownBy=WebStatsBreakdown.PAGE,
            properties=[],
            includeBounceRate=True,
            limit=10,
        )

        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        builder = StatsTablePreAggregatedQueryBuilder(runner)

        query_ast = builder.get_query()
        sql = self._print_select(query_ast)

        assert self.snapshot == sql

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_initial_page_breakdown_with_bounce_rate_query_generation(self):
        """Test query generation for initial page breakdown with bounce rate using state aggregations."""
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-02"),
            breakdownBy=WebStatsBreakdown.INITIAL_PAGE,
            properties=[],
            includeBounceRate=True,
            limit=10,
        )

        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        builder = StatsTablePreAggregatedQueryBuilder(runner)

        query_ast = builder.get_query()
        sql = self._print_select(query_ast)

        assert self.snapshot == sql

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_utm_source_breakdown_with_comparison_period(self):
        """Test query generation for UTM source breakdown with comparison period using state aggregations."""
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-01-08", date_to="2023-01-15"),
            breakdownBy=WebStatsBreakdown.INITIAL_UTM_SOURCE,
            properties=[],
            compareFilter=CompareFilter(compare=True, compare_to="previous_period"),
            limit=10,
        )

        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        builder = StatsTablePreAggregatedQueryBuilder(runner)

        query_ast = builder.get_query()
        sql = self._print_select(query_ast)

        assert self.snapshot == sql

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_country_breakdown_with_filters(self):
        """Test query generation for country breakdown with property filters using state aggregations."""
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-02"),
            breakdownBy=WebStatsBreakdown.COUNTRY,
            properties=[EventPropertyFilter(key="$browser", value="Chrome", operator="exact", type="event")],
            limit=10,
        )

        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        builder = StatsTablePreAggregatedQueryBuilder(runner)

        query_ast = builder.get_query()
        sql = self._print_select(query_ast)

        assert self.snapshot == sql

    @pytest.mark.usefixtures("unittest_snapshot")
    @patch(
        "posthog.hogql_queries.web_analytics.stats_table_pre_aggregated.StatsTablePreAggregatedQueryBuilder.can_use_preaggregated_tables"
    )
    def test_fallback_to_regular_query_when_preaggregated_not_available(self, mock_can_use):
        """Test that the runner falls back to regular queries when pre-aggregated tables can't be used."""
        mock_can_use.return_value = False

        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-02"),
            breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
            properties=[],
            limit=10,
        )

        # Disable pre-aggregated tables to test fallback
        runner = WebStatsTableQueryRunner(team=self.team, query=query)

        query_ast = runner.to_query()
        sql = self._print_select(query_ast)

        # Should use the regular query path (with uniq, count instead of merge functions)
        assert self.snapshot == sql

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_complex_stats_table_with_state_aggregations(self):
        """Test complex stats table query combining multiple state aggregation functions."""
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-01-01", date_to="2023-01-07"),
            breakdownBy=WebStatsBreakdown.VIEWPORT,
            properties=[],
            compareFilter=CompareFilter(compare=True, compare_to="previous_period"),
            orderBy=(WebAnalyticsOrderByFields.VIEWS, WebAnalyticsOrderByDirection.DESC),
            limit=5,
        )

        runner = WebStatsTableQueryRunner(team=self.team, query=query)
        builder = StatsTablePreAggregatedQueryBuilder(runner)

        query_ast = builder.get_query()
        sql = self._print_select(query_ast)

        # Verify it uses merge functions for state aggregations
        assert "uniqMergeIf" in sql
        assert "sumMergeIf" in sql
        assert self.snapshot == sql

    def _print_select(self, expr: ast.SelectQuery | ast.SelectSetQuery):
        """Helper method to print AST as formatted SQL."""
        query = print_ast(
            expr,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "clickhouse",
        )
        return pretty_print_in_tests(query, self.team.pk)
