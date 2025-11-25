from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events

from posthog.schema import (
    ActionConversionGoal,
    DateRange,
    HogQLQueryModifiers,
    SessionTableVersion,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.clickhouse.client.execute import sync_execute
from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.test.web_preaggregated_test_base import WebAnalyticsPreAggregatedTestBase
from posthog.models import Action
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_STATS_INSERT_SQL


class TestWebStatsTablePreAggregatedConversions(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self, user_prefix="user"):
        with freeze_time("2024-01-01T09:00:00Z"):
            _create_person(team_id=self.team.pk, distinct_ids=[f"{user_prefix}1"])
            _create_person(team_id=self.team.pk, distinct_ids=[f"{user_prefix}2"])

        # Use uuid7 with different timestamps to generate unique session IDs
        self.session1_id = str(uuid7("2024-01-01T10:00:00"))
        self.session2_id = str(uuid7("2024-01-01T11:00:00"))

        # Session 1: visits /page1 and converts
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=f"{user_prefix}1",
            timestamp="2024-01-01T10:00:00Z",
            properties={
                "$session_id": self.session1_id,
                "$current_url": "https://example.com/page1",
                "$pathname": "/page1",
            },
        )

        # Session 2: visits /page2 but doesn't convert
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=f"{user_prefix}2",
            timestamp="2024-01-01T11:00:00Z",
            properties={
                "$session_id": self.session2_id,
                "$current_url": "https://example.com/page2",
                "$pathname": "/page2",
            },
        )

        flush_persons_and_events()

    def test_conversion_goal_with_preaggregated_tables(self):
        """Test that conversion goals work with pre-aggregated tables by using hybrid approach"""
        self._setup_test_data(user_prefix="hybrid")

        # Create a conversion action
        action = Action.objects.create(
            team=self.team,
            name="Converted",
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "/page1",
                    "url_matching": "contains",
                }
            ],
        )

        # Populate pre-aggregated stats table with visitor data
        sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], select_only=True
        )
        sync_execute(f"INSERT INTO web_pre_aggregated_stats {sql}")

        with freeze_time("2024-01-02T00:00:00Z"):
            modifiers = HogQLQueryModifiers(
                sessionTableVersion=SessionTableVersion.V2,
                useWebAnalyticsPreAggregatedTables=True,
            )
            query = WebStatsTableQuery(
                dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
                breakdownBy=WebStatsBreakdown.PAGE,
                conversionGoal=ActionConversionGoal(actionId=action.id),
                properties=[],
            )
            runner = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers)

            # Verify pre-aggregated tables can be used
            assert runner.preaggregated_query_builder.can_use_preaggregated_tables()

            # Execute the query
            response = runner.calculate()

            # Verify we get conversion data
            assert response.results is not None
            assert len(response.results) >= 2  # At least 2 pages

            # Verify columns include conversion metrics
            assert response.columns is not None
            assert "context.columns.visitors" in response.columns
            assert "context.columns.total_conversions" in response.columns
            assert "context.columns.unique_conversions" in response.columns
            assert "context.columns.conversion_rate" in response.columns

            # Find the row with the conversion
            page1_row = next((row for row in response.results if row[0] == "/page1"), None)
            assert page1_row is not None
            visitors_current, visitors_previous = page1_row[1]
            total_conversions_current, total_conversions_previous = page1_row[2]
            unique_conversions_current, unique_conversions_previous = page1_row[3]
            conversion_rate_current, conversion_rate_previous = page1_row[4]

            # Page1 should have at least 1 visitor and 1 conversion
            assert visitors_current >= 1
            assert total_conversions_current >= 1.0
            assert unique_conversions_current >= 1.0
            assert conversion_rate_current > 0

            # Page 2 should have no conversions
            page2_row = next((row for row in response.results if row[0] == "/page2"), None)
            assert page2_row is not None

            visitors_current, visitors_previous = page2_row[1]
            total_conversions_current, total_conversions_previous = page2_row[2]
            unique_conversions_current, unique_conversions_previous = page2_row[3]
            conversion_rate_current, conversion_rate_previous = page2_row[4]

            # Page2 should have visitors but no conversions
            assert visitors_current >= 1
            assert total_conversions_current == 0.0
            assert unique_conversions_current == 0.0
            assert conversion_rate_current == 0.0

    def test_conversion_goal_with_preaggregated_tables_bounce_style(self):
        """Test conversion goals using bounce-rate-style query pattern (alternative implementation)"""
        from posthog.hogql_queries.web_analytics.stats_table_pre_aggregated import StatsTablePreAggregatedQueryBuilder

        # Enable bounce-style query for this test
        original_flag = StatsTablePreAggregatedQueryBuilder.USE_BOUNCE_STYLE_CONVERSION_QUERY
        StatsTablePreAggregatedQueryBuilder.USE_BOUNCE_STYLE_CONVERSION_QUERY = True

        try:
            self._setup_test_data(user_prefix="bounce")

            action = Action.objects.create(
                team=self.team,
                name="Converted",
                steps_json=[
                    {
                        "event": "$pageview",
                        "url": "/page1",
                        "url_matching": "contains",
                    }
                ],
            )

            # Populate pre-aggregated stats table with visitor data
            sql = WEB_STATS_INSERT_SQL(
                date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], select_only=True
            )
            sync_execute(f"INSERT INTO web_pre_aggregated_stats {sql}")

            with freeze_time("2024-01-02T00:00:00Z"):
                modifiers = HogQLQueryModifiers(
                    sessionTableVersion=SessionTableVersion.V2,
                    useWebAnalyticsPreAggregatedTables=True,
                )
                query = WebStatsTableQuery(
                    dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
                    breakdownBy=WebStatsBreakdown.PAGE,
                    conversionGoal=ActionConversionGoal(actionId=action.id),
                    properties=[],
                )
                runner = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers)

                # Verify pre-aggregated tables can be used
                assert runner.preaggregated_query_builder.can_use_preaggregated_tables()

                # Execute the query
                response = runner.calculate()

                # Verify we get conversion data
                assert response.results is not None
                assert len(response.results) >= 2  # At least 2 pages

                # Verify columns include conversion metrics
                assert response.columns is not None
                assert "context.columns.visitors" in response.columns
                assert "context.columns.total_conversions" in response.columns
                assert "context.columns.unique_conversions" in response.columns
                assert "context.columns.conversion_rate" in response.columns

                # Find the row with the conversion
                page1_row = next((row for row in response.results if row[0] == "/page1"), None)
                assert page1_row is not None
                visitors_current, visitors_previous = page1_row[1]
                total_conversions_current, total_conversions_previous = page1_row[2]
                unique_conversions_current, unique_conversions_previous = page1_row[3]
                conversion_rate_current, conversion_rate_previous = page1_row[4]

                # Page1 should have at least 1 visitor and 1 conversion
                assert visitors_current >= 1
                assert total_conversions_current >= 1.0
                assert unique_conversions_current >= 1.0
                assert conversion_rate_current > 0

                # Page 2 should have no conversions
                page2_row = next((row for row in response.results if row[0] == "/page2"), None)
                assert page2_row is not None

                visitors_current, visitors_previous = page2_row[1]
                total_conversions_current, total_conversions_previous = page2_row[2]
                unique_conversions_current, unique_conversions_previous = page2_row[3]
                conversion_rate_current, conversion_rate_previous = page2_row[4]

                # Page2 should have visitors but no conversions
                assert visitors_current >= 1
                assert total_conversions_current == 0.0
                assert unique_conversions_current == 0.0
                assert conversion_rate_current == 0.0
        finally:
            # Restore original flag value
            StatsTablePreAggregatedQueryBuilder.USE_BOUNCE_STYLE_CONVERSION_QUERY = original_flag
