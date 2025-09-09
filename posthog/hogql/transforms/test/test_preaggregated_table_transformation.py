from datetime import UTC, datetime

import unittest
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, QueryMatchingTest, snapshot_clickhouse_queries

from parameterized import parameterized

from posthog.schema import BaseMathType, DateRange, EventsNode, HogQLQueryModifiers, TrendsQuery

from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.web_analytics_preaggregated import WebStatsCombinedTable
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.transforms.preaggregated_table_transformation import (
    PREAGGREGATED_TABLE_NAME,
    do_preaggregated_table_transforms,
    is_integer_timezone,
)

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.web_analytics.pre_aggregated.properties import (
    EVENT_PROPERTY_TO_FIELD,
    SESSION_PROPERTY_TO_FIELD,
)
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP


class TestPreaggregatedTableTransformation(BaseTest, QueryMatchingTest):
    @parameterized.expand(EVENT_PROPERTY_TO_FIELD.items())
    def test_all_event_properties_on_events_supported(self, property_name, field_name):
        original_query = (
            f"select count(), uniq(person_id) from events where event = '$pageview' group by properties.{property_name}"
        )
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    @parameterized.expand(SESSION_PROPERTY_TO_FIELD.items())
    def test_all_session_properties_on_events_unsupported(self, property_name, field_name):
        original_query = (
            f"select count(), uniq(person_id) from events where event = '$pageview' group by properties.{property_name}"
        )
        query = self._parse_and_transform(original_query)
        # Query is preserved - no transformation, these are invalid event properties
        assert PREAGGREGATED_TABLE_NAME not in query
        assert query == self._normalize(original_query)

    @parameterized.expand(EVENT_PROPERTY_TO_FIELD.items())
    def test_all_event_properties_on_session_unsupported(self, property_name, field_name):
        original_query = (
            f"select count(), uniq(person_id) from events where event = '$pageview' group by session.{property_name}"
        )
        query = self._parse_and_transform(original_query)
        # Query is preserved - no transformation, these are invalid session properties
        assert PREAGGREGATED_TABLE_NAME not in query
        assert query == self._normalize(original_query)

    @parameterized.expand(SESSION_PROPERTY_TO_FIELD.items())
    def test_all_session_properties_on_sessions_supported(self, property_name, field_name):
        original_query = (
            f"select count(), uniq(person_id) from events where event = '$pageview' group by session.{property_name}"
        )
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def _parse_and_transform(self, query: str):
        node = parse_select(query)
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        transformed = do_preaggregated_table_transforms(node, context)
        return str(transformed)

    def _normalize(self, query: str):
        node = parse_select(query)
        return str(node)

    def test_preaggregation_tables(self):
        original_query = """
            select
                count(),
                count(*),
                uniq(person_id),
                uniq(events.person_id),
                uniq(person.id),
                uniq(events.person.id),
                count(DISTINCT person_id),
                uniq(session.id),
                uniq(events.session.id),
                uniq($session_id),
                uniq(events.$session_id),
                count(DISTINCT session.id)
            from events
            where event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_wrong_id(self):
        original_query = """
            select
                uniq(id)
            from events
            where event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME not in query
        assert query == self._normalize(original_query)

    def test_wrong_aggregation_function(self):
        original_query = """
            select
                count(person_id)
            from events
            where event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME not in query
        assert query == self._normalize(original_query)

    def test_no_aggregation_function(self):
        original_query = """
            select
                1
            from events
            where event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME not in query
        assert query == self._normalize(original_query)

    def test_nested_preaggregation_tables(self):
        original_query = "select * from (select count(), uniq(person_id) from events where event = '$pageview')"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_equals_function(self):
        original_query = "select count(), uniq(person_id) from events where equals(event, '$pageview')"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_unsupported_event(self):
        original_query = "select count(), uniq(person_id) from events where equals(event, 'other event')"
        query = self._parse_and_transform(original_query)
        # Query is preserved - wrong event
        assert PREAGGREGATED_TABLE_NAME not in query
        expected = self._normalize(original_query)
        assert query == expected

    def test_no_event(self):
        original_query = "select count(), uniq(person_id) from events"
        query = self._parse_and_transform(original_query)
        # Query is preserved - no event filter
        assert PREAGGREGATED_TABLE_NAME not in query
        expected = self._normalize(original_query)
        assert query == expected

    def test_supported_and_unsupported_event(self):
        original_query = "select count(), uniq(person_id) from events where equals(event, '$pageview') or equals(event, 'other event')"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME not in query
        # Query is preserved - no transformation due to mixed events
        expected = self._normalize(original_query)
        assert query == expected

    def test_sample_1(self):
        original_query = "select count(), uniq(person_id) from events sample 1 where event = '$pageview'"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_sample_not_1(self):
        original_query = "select count(), uniq(person_id) from events sample 0.5 where event = '$pageview'"
        query = self._parse_and_transform(original_query)
        # Query is preserved - no transformation due to unsupported sample rate
        assert PREAGGREGATED_TABLE_NAME not in query
        expected = self._normalize(original_query)
        assert query == expected

    def test_preaggregation_tables_group_by_supported(self):
        original_query = (
            "select count(), uniq(person_id) from events where event = '$pageview' group by properties.utm_source"
        )
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_preaggregation_tables_group_by_not_supported(self):
        original_query = "select count(), uniq(person_id) from events where event = '$pageview' group by properties.not_supported_property"
        query = self._parse_and_transform(original_query)
        # Query is preserved - no transformation due to unsupported group by field
        assert PREAGGREGATED_TABLE_NAME not in query
        expected = self._normalize(original_query)
        assert query == expected

    def test_preaggregation_tables_group_by_session_property(self):
        original_query = (
            "select count(), uniq(person_id) from events where event = '$pageview' group by session.$entry_pathname"
        )
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_group_by_property(self):
        original_query = "select count(), uniq(person_id) from events where event = '$pageview' group by properties.utm_source, events.properties.utm_campaign, session.$entry_pathname, events.session.$end_pathname"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_group_by_alias_supported(self):
        original_query = "select count(), uniq(person_id), properties.utm_source as u from events where event = '$pageview' group by u"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_group_by_alias_not_supported(self):
        original_query = "select count(), uniq(person_id), properties.not_supported_property as n from events where event = '$pageview' group by n"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME not in query
        assert query == self._normalize(original_query)

    def test_group_by_start_of_day(self):
        original_query = "SELECT count() AS total, toStartOfDay(e.timestamp) AS day_start FROM events WHERE event = '$pageview' GROUP BY day_start"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_group_by_and_where(self):
        original_query = "SELECT count() AS total, toStartOfDay(e.timestamp) AS day_start, properties.utm_source as u FROM events WHERE event = '$pageview' AND ifNull(u, 'null') GROUP BY day_start, u"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_unsupported_table(self):
        original_query = "select count(), uniq(person_id) from not_events where equals(event, '$pageview')"
        query = self._parse_and_transform(original_query)
        # Query is preserved - wrong table
        assert PREAGGREGATED_TABLE_NAME not in query
        expected = self._normalize(original_query)
        assert query == expected

    def test_alias_intact(self):
        original_query = "select count() as c, uniq(person_id) as p, uniq($session_id) as s, properties.utm_medium as m from events where event = '$pageview' group by m"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_all_supported_event_properties_are_in_taxonomy(self):
        for property_name in EVENT_PROPERTY_TO_FIELD.keys():
            # Skip custom metadata properties that are customer-specific
            if property_name.startswith("metadata.loggedIn") or property_name.startswith("metadata.backend"):
                continue
            assert property_name in CORE_FILTER_DEFINITIONS_BY_GROUP["event_properties"].keys()

    def test_all_supported_session_properties_are_in_taxonomy(self):
        for property_name in SESSION_PROPERTY_TO_FIELD.keys():
            assert property_name in CORE_FILTER_DEFINITIONS_BY_GROUP["session_properties"].keys()

    def test_all_supported_event_properties_are_in_stats_table(self):
        for property_name in EVENT_PROPERTY_TO_FIELD.values():
            assert property_name in WebStatsCombinedTable().fields.keys()

    def test_all_supported_session_properties_are_in_stats_table(self):
        for property_name in SESSION_PROPERTY_TO_FIELD.values():
            assert property_name in WebStatsCombinedTable().fields.keys()

    def test_multiple_ctes_transformation(self):
        """Test that multiple CTEs can get transformed independently."""
        original_query = """
            WITH
                pageview_stats AS (
                    SELECT count() as pageviews, uniq(person_id) as users
                    FROM events
                    WHERE event = '$pageview'
                ),
                regular_events AS (
                    SELECT count() as total_events, uniq(person_id) as total_users
                    FROM events
                    WHERE event = 'custom_event'
                ),
                another_pageview_cte AS (
                    SELECT count() as more_pageviews, properties.utm_source as source
                    FROM events
                    WHERE event = '$pageview'
                    GROUP BY properties.utm_source
                )
            SELECT
                pageview_stats.pageviews,
                pageview_stats.users,
                regular_events.total_events,
                regular_events.total_users,
                another_pageview_cte.more_pageviews,
                another_pageview_cte.source
            FROM pageview_stats
            CROSS JOIN regular_events
            CROSS JOIN another_pageview_cte
        """

        # The assertions here are pretty odd, as debug printing of hogql queries with CTEs does not work.
        node = parse_select(original_query)
        context = HogQLContext(team_id=self.team.pk, team=self.team)
        transformed = do_preaggregated_table_transforms(node, context)
        assert isinstance(transformed, SelectQuery)

        # Verify that CTEs exist and are transformed correctly
        assert transformed.ctes is not None
        assert len(transformed.ctes) == 3
        assert "pageview_stats" in transformed.ctes
        assert "regular_events" in transformed.ctes
        assert "another_pageview_cte" in transformed.ctes

        # Check that pageview_stats CTE was transformed (should use web_stats_daily)
        pageview_stats_cte = transformed.ctes["pageview_stats"]
        pageview_stats_str = str(pageview_stats_cte.expr)
        assert PREAGGREGATED_TABLE_NAME in pageview_stats_str
        assert "sumMerge(pageviews_count_state)" in pageview_stats_str
        assert "uniqMerge(persons_uniq_state)" in pageview_stats_str

        # Check that regular_events CTE was NOT transformed (should still use events)
        regular_events_cte = transformed.ctes["regular_events"]
        regular_events_str = str(regular_events_cte.expr)
        assert "events" in regular_events_str
        assert PREAGGREGATED_TABLE_NAME not in regular_events_str
        assert "count()" in regular_events_str
        assert "uniq(person_id)" in regular_events_str

        # Check that another_pageview_cte CTE was transformed (should use web_stats_daily)
        another_pageview_cte = transformed.ctes["another_pageview_cte"]
        another_pageview_str = str(another_pageview_cte.expr)
        assert PREAGGREGATED_TABLE_NAME in another_pageview_str
        assert "sumMerge(pageviews_count_state)" in another_pageview_str
        assert "utm_source" in another_pageview_str

        # Check that the main query still references the CTEs correctly
        main_query_str = str(transformed)
        assert "pageview_stats.pageviews" in main_query_str
        assert "regular_events.total_events" in main_query_str
        assert "another_pageview_cte.more_pageviews" in main_query_str

    def test_nested_select_queries(self):
        """Test that nested SELECT queries within SELECT clauses are handled correctly."""
        original_query = """
            SELECT
                count() as total,
                (SELECT count() FROM events WHERE event = '$pageview') as pageviews
            FROM events
            WHERE event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        # The inner query should be transformed, but not the outer one
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_union_queries(self):
        """Test that UNION queries are handled properly."""
        original_query = """
            SELECT count() FROM events WHERE event = '$pageview'
            UNION ALL
            SELECT count() FROM events WHERE event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        # Both parts of the union should be transformed
        assert query.count("sumMerge(pageviews_count_state)") == 2
        assert query.count(PREAGGREGATED_TABLE_NAME) == 2
        self.assertQueryMatchesSnapshot(query)

    def test_mixed_aggregations_with_unsupported(self):
        """Test queries with both supported and unsupported aggregation functions."""
        original_query = """
            SELECT
                count() as pageviews,
                avg(person_id) as avg_person,
                uniq(person_id) as users
            FROM events
            WHERE event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME not in query
        # Should not transform because avg(person_id) is not supported
        assert query == self._normalize(original_query)

    def test_having_clause_preservation(self):
        """Test that HAVING clauses are preserved in transformations."""
        original_query = """
            SELECT count() as c, uniq(person_id) as u
            FROM events
            WHERE event = '$pageview'
            GROUP BY properties.utm_source
            HAVING c > 100
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_order_by_preservation(self):
        """Test that ORDER BY clauses are preserved."""
        original_query = """
            SELECT count() as c, uniq(person_id) as u
            FROM events
            WHERE event = '$pageview'
            GROUP BY properties.utm_source
            ORDER BY c DESC
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_limit_offset_preservation(self):
        """Test that LIMIT and OFFSET clauses are preserved."""
        original_query = """
            SELECT count(), uniq(person_id)
            FROM events
            WHERE event = '$pageview'
            LIMIT 10 OFFSET 5
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_complex_where_clause_with_and_or(self):
        """Test complex WHERE clauses with AND/OR that include pageview filter."""
        original_query = """
            SELECT count()
            FROM events
            WHERE (event = '$pageview' AND properties.utm_source IS NOT NULL)
               OR (event = '$pageview' AND properties.utm_medium = 'email')
        """
        query = self._parse_and_transform(original_query)
        # Should not transform due to complex OR logic with unsupported conditions
        assert PREAGGREGATED_TABLE_NAME not in query
        assert query == self._normalize(original_query)

    def test_simple_and_condition_transforms(self):
        """Test that simple AND conditions with only pageview filter transform correctly."""
        original_query = """
            SELECT count()
            FROM events
            WHERE event = '$pageview' AND plus(1,2) = 3
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_empty_select_query(self):
        """Test edge case with minimal SELECT query."""
        original_query = """
            SELECT count()
            FROM events
            WHERE event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_transformation_with_table_alias(self):
        """Test that table aliases are preserved correctly."""
        original_query = """
            SELECT count(), uniq(e.person_id)
            FROM events e
            WHERE e.event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        # The alias should be preserved even though we change the table
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_unsupported_group_by_session_property(self):
        """Test that unsupported session properties prevent transformation."""
        original_query = """
            SELECT count(), uniq(person_id)
            FROM events
            WHERE event = '$pageview'
            GROUP BY session.unsupported_property
        """
        query = self._parse_and_transform(original_query)
        # Should not transform due to unsupported session property
        assert PREAGGREGATED_TABLE_NAME not in query
        assert query == self._normalize(original_query)

    def test_mixed_supported_unsupported_properties_in_select(self):
        """Test queries that mix supported and unsupported properties in SELECT."""
        original_query = """
            SELECT
                count() as pageviews,
                properties.utm_source as source,
                properties.unsupported_prop as unsupported
            FROM events
            WHERE event = '$pageview'
            GROUP BY properties.utm_source, properties.unsupported_prop
        """
        query = self._parse_and_transform(original_query)
        # Should not transform due to unsupported property in GROUP BY
        assert PREAGGREGATED_TABLE_NAME not in query
        assert query == self._normalize(original_query)

    def test_window_functions_unsupported(self):
        """Test that window functions prevent transformation."""
        original_query = """
            SELECT
                count(),
                row_number() OVER (ORDER BY person_id) as row_num
            FROM events
            WHERE event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        # Should not transform due to window function
        assert PREAGGREGATED_TABLE_NAME not in query
        assert query == self._normalize(original_query)

    def test_subquery_in_where_clause(self):
        """Test that subqueries in WHERE clause are handled properly."""
        original_query = """
            SELECT count()
            FROM events
            WHERE event = '$pageview'
              AND person_id IN (SELECT id FROM persons WHERE created_at > '2023-01-01')
        """
        query = self._parse_and_transform(original_query)
        # Should not transform due to complex WHERE clause with subquery
        assert PREAGGREGATED_TABLE_NAME not in query
        assert query == self._normalize(original_query)

    def test_case_when_expressions(self):
        """Test that CASE WHEN expressions are handled correctly."""
        original_query = """
            SELECT
                count(),
                CASE WHEN properties.utm_source = 'google' THEN 'search' ELSE 'other' END as source_type
            FROM events
            WHERE event = '$pageview'
            GROUP BY source_type
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_arithmetic_in_select(self):
        """Test that arithmetic expressions with aggregations are not supported."""
        original_query = """
            SELECT count() * 2 as double_count
            FROM events
            WHERE event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_null_comparisons_unsupported(self):
        """Test that NULL comparisons beyond simple constants are unsupported."""
        original_query = """
            SELECT count()
            FROM events
            WHERE event = '$pageview' AND person_id IS NOT NULL
        """
        query = self._parse_and_transform(original_query)
        # Should not transform due to IS NOT NULL comparison
        assert PREAGGREGATED_TABLE_NAME not in query
        assert query == self._normalize(original_query)

    def test_start_of_day_timestamp_with_condition(self):
        """Test that a timestamp in the comparison is supported."""
        original_query = """
            SELECT count()
            FROM events
            WHERE event = '$pageview' AND toStartOfDay(timestamp) >= '2024-11-24'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_start_of_hour_timestamp_with_condition(self):
        original_query = """
            SELECT count()
            FROM events
            WHERE event = '$pageview' AND toStartOfHour(timestamp) >= '2024-11-24'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_start_of_week_timestamp_with_condition(self):
        original_query = """
            SELECT count()
            FROM events
            WHERE event = '$pageview' AND toStartOfWeek(timestamp) >= '2024-11-24'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_timestamp_with_start_of_day_condition(self):
        """This case is pretty tricky, it relies on assuming that toStartOfDay(timestamp) >= toStartOfDay('2024-11-24') is equivalent to timestamp >= toStartOfDay('2024-11-24')."""
        original_query = """
            SELECT
                count()
            FROM events
            WHERE event = '$pageview' AND timestamp >= toStartOfDay('2024-11-24')
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_timestamp_with_start_of_day_condition_reversed(self):
        original_query = """
            SELECT
                count()
            FROM events
            WHERE event = '$pageview' AND toStartOfDay('2024-11-24') <= timestamp
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_invalid_timestamp_condition(self):
        """This case relies on us knowing that this transformation is invalid."""
        original_query = """
            SELECT
                count()
            FROM events
            WHERE event = '$pageview' AND timestamp > toStartOfDay('2024-11-24')
        """
        query = self._parse_and_transform(original_query)
        assert query == self._normalize(original_query)

    def test_timestamp_string_day_condition(self):
        """This case relies on parsing the timestamp string to pick up that is at day-level resolution"""
        original_query = """
            SELECT
                count()
            FROM events
            WHERE event = '$pageview' AND timestamp >= '2024-11-24'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_timestamp_string_hour_condition(self):
        """This case relies on parsing the timestamp string to pick up that is at hour-level resolution"""
        original_query = """
            SELECT
                count()
            FROM events
            WHERE event = '$pageview' AND timestamp >= '2024-11-24T13:00:00'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_timestamp_end_of_day_string_condition(self):
        original_query = """
              SELECT
                  count()
              FROM events
              WHERE event = '$pageview' AND lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-11-24 23:59:59')))
          """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_to_start_of_interval_day_with_mid_day_timestamp(self):
        """This case relies on knowing that toStartOfInterval with a day corresponds to the start of a day."""
        original_query = """
              SELECT
                  count()
              FROM events
              WHERE event = '$pageview'
              AND greaterOrEquals(timestamp, toStartOfInterval(assumeNotNull(toDateTime('2025-07-10 14:04:24')), toIntervalDay(1)))
          """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_trends_line_inner_query(self):
        # This inner query comes from the default query in Product analytics
        original_query = """
        SELECT
            count() AS total,
            toStartOfDay(timestamp) AS day_start
        FROM
            events AS e SAMPLE 1
        WHERE
            and(greaterOrEquals(timestamp, toStartOfInterval(assumeNotNull(toDateTime('2025-07-10 14:04:24')), toIntervalDay(1))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2025-07-17 23:59:59'))), equals(event, '$pageview'))
        GROUP BY
            day_start"""
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_full_trends_line_query(self):
        original_query = """
SELECT
    arrayMap(number -> plus(toStartOfInterval(assumeNotNull(toDateTime('2025-07-10 14:04:24')), toIntervalDay(1)), toIntervalDay(number)), range(0, plus(coalesce(dateDiff('day', toStartOfInterval(assumeNotNull(toDateTime('2025-07-10 14:04:24')), toIntervalDay(1)), toStartOfInterval(assumeNotNull(toDateTime('2025-07-17 23:59:59')), toIntervalDay(1)))), 1))) AS date,
    arrayMap(_match_date -> arraySum(arraySlice(groupArray(ifNull(count, 0)), indexOf(groupArray(day_start) AS _days_for_count, _match_date) AS _index, plus(minus(arrayLastIndex(x -> equals(x, _match_date), _days_for_count), _index), 1))), date) AS total
FROM
    (SELECT
        sum(total) AS count,
        day_start
    FROM
        (SELECT
            count() AS total,
            toStartOfDay(timestamp) AS day_start
        FROM
            events AS e SAMPLE 1
        WHERE
            and(greaterOrEquals(timestamp, toStartOfInterval(assumeNotNull(toDateTime('2025-07-10 14:04:24')), toIntervalDay(1))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2025-07-17 23:59:59'))), equals(event, '$pageview'))
        GROUP BY
            day_start)
    GROUP BY
        day_start
    ORDER BY
        day_start ASC)
ORDER BY
    arraySum(total) DESC
LIMIT 50000
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_full_trends_query_clickhouse(self):
        original_query = """
SELECT arrayMap(number -> plus(toStartOfInterval(assumeNotNull(toDateTime('2025-07-10 20:59:19')), toIntervalDay(1)), toIntervalDay(number)), range(0, plus(coalesce(dateDiff('day', toStartOfInterval(assumeNotNull(toDateTime('2025-07-10 20:59:19')), toIntervalDay(1)), toStartOfInterval(assumeNotNull(toDateTime('2025-07-17 23:59:59')), toIntervalDay(1)))), 1))) AS date, arrayMap(_match_date -> arraySum(arraySlice(groupArray(ifNull(count, 0)), indexOf(groupArray(day_start) AS _days_for_count, _match_date) AS _index, plus(minus(arrayLastIndex(x -> equals(x, _match_date), _days_for_count), _index), 1))), date) AS total FROM (SELECT sum(total) AS count, day_start FROM (SELECT count() AS total, toStartOfDay(timestamp) AS day_start FROM events AS e SAMPLE 1 WHERE and(greaterOrEquals(timestamp, toStartOfInterval(assumeNotNull(toDateTime('2025-07-10 20:59:19')), toIntervalDay(1))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2025-07-17 23:59:59'))), equals(event, '$pageview')) GROUP BY day_start) GROUP BY day_start ORDER BY day_start ASC) ORDER BY arraySum(total) DESC LIMIT 50000
            """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_trends_pie_inner_query(self):
        # This inner query comes from the default query in Trends pie chart
        original_query = """
SELECT
    count() AS total
FROM
    events AS e SAMPLE 1
WHERE
    and(equals(e.team_id, 1), greaterOrEquals(toTimeZone(e.timestamp, 'UTC'), toStartOfInterval(assumeNotNull(toDateTime('2025-07-11 00:00:00', 'UTC')), toIntervalDay(1))), lessOrEquals(toTimeZone(e.timestamp, 'UTC'), assumeNotNull(toDateTime('2025-07-18 23:59:59', 'UTC'))), equals(e.event, '$pageview'))
ORDER BY
    1 DESC
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_tuple(self):
        original_query = """
        SELECT
            (uniq(person_id), count(), uniq(session.id)) AS daily_metrics
        FROM events
        WHERE event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    @unittest.expectedFailure
    def test_if_functions_instead_of_where(self):
        original_query = """
        SELECT
            uniqIf(person_id, event = '$pageview') AS unique_users,
            countIf(event = '$pageview') AS pageviews,
            sumIf(1, event = '$pageview') AS total_pageviews,
            uniqIf(session.id, event = '$pageview') AS unique_sessions
FROM events
WHERE toDate(timestamp) >= now() - interval 1 hour
GROUP BY date
        """
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_integer_timezones(self):
        assert is_integer_timezone("UTC")
        assert is_integer_timezone("Europe/London")
        assert is_integer_timezone("America/New_York")
        assert not is_integer_timezone("Asia/Kathmandu")  # UTC+5:45
        assert not is_integer_timezone("Asia/Kolkata")  # UTC+5:30
        assert not is_integer_timezone("Australia/Adelaide")  # UTC+9:30

    def test_enable_for_integer_team_timezones(self):
        self.team.timezone = "Europe/London"
        self.team.save()
        original_query = "select count(), uniq(person_id) from events where event = '$pageview'"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME in query
        self.assertQueryMatchesSnapshot(query)

    def test_disable_for_non_integer_team_timezones(self):
        self.team.timezone = "Asia/Kathmandu"
        self.team.save()
        original_query = "select count(), uniq(person_id) from events where event = '$pageview'"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME not in query

    def test_disable_for_invalid_team_timezones(self):
        self.team.timezone = "Not/A Timezone"
        self.team.save()
        original_query = "select count(), uniq(person_id) from events where event = '$pageview'"
        query = self._parse_and_transform(original_query)
        assert PREAGGREGATED_TABLE_NAME not in query


@snapshot_clickhouse_queries
class TestPreaggregatedTableTransformationIntegration(APIBaseTest, ClickhouseTestMixin):
    CLASS_DATA_LEVEL_SETUP = False
    TEST_DATA_DATE = datetime(2024, 11, 24, tzinfo=UTC)

    def _insert_stats_row(self, period_bucket=None):
        if not period_bucket:
            period_bucket = f"toStartOfDay(toDateTime('{self.TEST_DATA_DATE.strftime('%Y-%m-%d')}'))"
        sql = f"""
     INSERT INTO web_pre_aggregated_stats (
         period_bucket,
         team_id,
         host,
         device_type,
         pathname,
         entry_pathname,
         end_pathname,
         browser,
         os,
         viewport_width,
         viewport_height,
         referring_domain,
         utm_source,
         utm_medium,
         utm_campaign,
         utm_term,
         utm_content,
         country_code,
         city_name,
         region_code,
         region_name,
         has_gclid,
         has_gad_source_paid_search,
         has_fbclid,
         persons_uniq_state,
         sessions_uniq_state,
         pageviews_count_state
     ) SELECT
         {period_bucket} as period_bucket,
         {self.team.id} as team_id,
         '' as host,
         '' as device_type,

         '' as pathname,
         '' as entry_pathname,
         '' as end_pathname,
         '' as browser,
         '' as os,
         0 as viewport_width,
         0 as viewport_height,
         '' as referring_domain,
         '' as utm_source,
         '' as utm_medium,
         '' as utm_campaign,
         '' as utm_term,
         '' as utm_content,
         '' as country_code,
         '' as city_name,
         '' as region_code,
         '' as region_name,
         false as has_gclid,
         false as has_gad_source_paid_search,
         false as has_fbclid,

         initializeAggregation('uniqState', generateUUIDv7()) as persons_uniq,
         initializeAggregation('uniqState', toString(generateUUIDv7())) as sessions_uniq,
         initializeAggregation('sumState', toUInt64(1)) as pageview_state
         """
        sync_execute(sql, flush=True)

    def test_basic_hogql_query(self):
        """Test that trends queries are handled correctly."""
        # add a pageview to the combined table, so that we can be sure we are fetching the correct table
        self._insert_stats_row()

        response = execute_hogql_query(
            parse_select("select count(), uniq(person_id) from events where equals(event, '$pageview')"),
            team=self.team,
            modifiers=HogQLQueryModifiers(usePreaggregatedTableTransforms=True),
        )
        assert response.hogql and PREAGGREGATED_TABLE_NAME in response.hogql
        assert response.results == [(1, 1)]

    def test_complex_hogql_select(self):
        """Test that complex HogQL queries are handled correctly."""
        # add a pageview to the combined table, so that we can be sure we are fetching the correct table
        self._insert_stats_row()

        response = execute_hogql_query(
            parse_select(
                "select count() as c, uniq(person_id) as p, uniq($session_id) as s, toStartOfDay(timestamp) as t, properties.utm_source as u from events where equals(event, '$pageview') and properties.utm_campaign == '' group by t, u, properties.utm_medium having c > 0 and u == ''"
            ),
            team=self.team,
            modifiers=HogQLQueryModifiers(usePreaggregatedTableTransforms=True),
        )
        assert response.hogql and PREAGGREGATED_TABLE_NAME in response.hogql
        assert len(response.results) == 1
        row = response.results[0]
        assert row[0:3] == (1, 1, 1)
        assert isinstance(row[3], datetime)
        assert row[4] == ""

    def test_hogql_inner_trend(self):
        # execute a hogql query that roughly matchs the inner query of a trends query
        self._insert_stats_row()
        original_query = """
            SELECT
                count() AS total,
                toStartOfDay(timestamp) AS day_start
            FROM events AS e
            SAMPLE 1
            WHERE
                and(
                    greaterOrEquals(timestamp, toStartOfInterval(assumeNotNull(toDateTime('2024-11-22 00:00:00')), toIntervalDay(1))),
                    lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-11-26 23:59:59'))), equals(event, '$pageview')
                )
            GROUP BY day_start
        """
        response = execute_hogql_query(
            parse_select(original_query),
            team=self.team,
            modifiers=HogQLQueryModifiers(usePreaggregatedTableTransforms=True),
        )
        assert response.results == [(1, self.TEST_DATA_DATE)]

    def test_trends_query(self):
        """Test that trends queries are handled correctly."""
        # add a pageview to the combined table, so that we can be sure we are fetching the correct table
        self._insert_stats_row()

        original_query = TrendsQuery(
            series=[EventsNode(name="$pageview", event="$pageview", math=BaseMathType.TOTAL)],
            dateRange=DateRange(date_from="2024-11-22", date_to="2024-11-26"),
            modifiers=HogQLQueryModifiers(usePreaggregatedTableTransforms=True),
        )
        tqr = TrendsQueryRunner(team=self.team, query=original_query)
        response = tqr.calculate()
        assert len(response.results) == 1
        series = response.results[0]
        assert series["count"] == 1
        assert series["days"] == [
            "2024-11-22",
            "2024-11-23",
            "2024-11-24",
            "2024-11-25",
            "2024-11-26",
        ]
        assert series["data"] == [0, 0, 1, 0, 0]

    def test_trends_line_dau_query(self):
        """Test that trends dau queries are handled correctly."""
        # add a pageview to the combined table, so that we can be sure we are fetching the correct table
        self._insert_stats_row()

        original_query = TrendsQuery(
            series=[EventsNode(name="$pageview", event="$pageview", math=BaseMathType.DAU)],
            dateRange=DateRange(date_from="2024-11-22", date_to="2024-11-26"),
            modifiers=HogQLQueryModifiers(usePreaggregatedTableTransforms=True),
        )
        tqr = TrendsQueryRunner(team=self.team, query=original_query)
        response = tqr.calculate()
        assert len(response.results) == 1
        series = response.results[0]
        assert series["count"] == 1
        assert series["days"] == [
            "2024-11-22",
            "2024-11-23",
            "2024-11-24",
            "2024-11-25",
            "2024-11-26",
        ]
        assert series["data"] == [0, 0, 1, 0, 0]
