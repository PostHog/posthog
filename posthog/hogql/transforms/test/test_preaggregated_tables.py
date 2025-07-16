from posthog.hogql.ast import SelectQuery
from posthog.hogql.database.schema.web_analytics_preaggregated import (
    EVENT_PROPERTY_TO_FIELD,
    SESSION_PROPERTY_TO_FIELD,
    WebStatsCombinedTable,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.preaggregated_tables import do_preaggregated_table_transforms
from posthog.hogql.context import HogQLContext
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP
from posthog.test.base import BaseTest
from parameterized import parameterized


class TestPreaggregatedTables(BaseTest):
    def _parse_and_transform(self, query: str):
        node = parse_select(query)
        context = HogQLContext(team_id=self.team.pk)
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
                uniq(events.person.id),
                uniq(session.id),
                uniq(events.$session_id)
            from events
            where event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        expected = """sql(SELECT sumMerge(pageviews_count_state), sumMerge(pageviews_count_state), uniqMerge(persons_uniq_state), uniqMerge(persons_uniq_state), uniqMerge(sessions_uniq_state), uniqMerge(sessions_uniq_state) FROM web_stats_combined)"""
        assert query == expected

    def test_wrong_id(self):
        original_query = """
            select
                uniq(id)
            from events
            where event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        assert query == self._normalize(original_query)

    def test_wrong_aggregation_function(self):
        original_query = """
            select
                count(person_id)
            from events
            where event = '$pageview'
        """
        query = self._parse_and_transform(original_query)
        assert query == self._normalize(original_query)

    def test_nested_preaggregation_tables(self):
        original_query = "select * from (select count(), uniq(person_id) from events where event = '$pageview')"
        query = self._parse_and_transform(original_query)
        expected = """sql(SELECT * FROM (SELECT sumMerge(pageviews_count_state), uniqMerge(persons_uniq_state) FROM web_stats_combined))"""
        assert query == expected

    def test_equals_function(self):
        original_query = "select count(), uniq(person_id) from events where equals(event, '$pageview')"
        query = self._parse_and_transform(original_query)
        expected = (
            """sql(SELECT sumMerge(pageviews_count_state), uniqMerge(persons_uniq_state) FROM web_stats_combined)"""
        )
        assert query == expected

    def test_unsupported_event(self):
        original_query = "select count(), uniq(person_id) from events where equals(event, 'other event')"
        query = self._parse_and_transform(original_query)
        # Query is preserved - wrong event
        expected = self._normalize(original_query)
        assert query == expected

    def test_no_event(self):
        original_query = "select count(), uniq(person_id) from events"
        query = self._parse_and_transform(original_query)
        # Query is preserved - no event filter
        expected = self._normalize(original_query)
        assert query == expected

    def test_supported_and_unsupported_event(self):
        original_query = "select count(), uniq(person_id) from events where equals(event, '$pageview') or equals(event, 'other event')"
        query = self._parse_and_transform(original_query)
        # Query is preserved - no transformation due to mixed events
        expected = self._normalize(original_query)
        assert query == expected

    def test_sample_1(self):
        original_query = "select count(), uniq(person_id) from events sample 1 where event = '$pageview'"
        query = self._parse_and_transform(original_query)
        expected = (
            """sql(SELECT sumMerge(pageviews_count_state), uniqMerge(persons_uniq_state) FROM web_stats_combined)"""
        )
        assert query == expected

    def test_sample_not_1(self):
        original_query = "select count(), uniq(person_id) from events sample 0.5 where event = '$pageview'"
        query = self._parse_and_transform(original_query)
        # Query is preserved - no transformation due to unsupported sample rate
        expected = self._normalize(original_query)
        assert query == expected

    def test_preaggregation_tables_group_by_supported(self):
        original_query = (
            "select count(), uniq(person_id) from events where event = '$pageview' group by properties.utm_source"
        )
        query = self._parse_and_transform(original_query)
        expected = """sql(SELECT sumMerge(pageviews_count_state), uniqMerge(persons_uniq_state) FROM web_stats_combined GROUP BY utm_source)"""
        assert query == expected

    def test_preaggregation_tables_group_by_not_supported(self):
        original_query = "select count(), uniq(person_id) from events where event = '$pageview' group by properties.not_supported_property"
        query = self._parse_and_transform(original_query)
        # Query is preserved - no transformation due to unsupported group by field
        expected = self._normalize(original_query)
        assert query == expected

    def test_preaggregation_tables_group_by_session_property(self):
        original_query = (
            "select count(), uniq(person_id) from events where event = '$pageview' group by session.$entry_pathname"
        )
        query = self._parse_and_transform(original_query)
        expected = """sql(SELECT sumMerge(pageviews_count_state), uniqMerge(persons_uniq_state) FROM web_stats_combined GROUP BY entry_pathname)"""
        assert query == expected

    def test_group_by_alias_supported(self):
        original_query = "select count(), uniq(person_id), properties.utm_source as u from events where event = '$pageview' group by u"
        query = self._parse_and_transform(original_query)
        expected = """sql(SELECT sumMerge(pageviews_count_state), uniqMerge(persons_uniq_state), utm_source AS u FROM web_stats_combined GROUP BY u)"""
        assert query == expected

    def test_group_by_alias_not_supported(self):
        original_query = "select count(), uniq(person_id), properties.not_supported_property as n from events where event = '$pageview' group by n"
        query = self._parse_and_transform(original_query)
        expected = """sql(SELECT sumMerge(pageviews_count_state), uniqMerge(persons_uniq_state), properties.not_supported_property AS n FROM web_stats_combined GROUP BY n)"""
        assert query == expected

    def test_group_by_start_of_day(self):
        original_query = "SELECT count() AS total, toStartOfDay(e.timestamp) AS day_start FROM events WHERE event = '$pageview' GROUP BY day_start"
        query = self._parse_and_transform(original_query)
        expected = """sql(SELECT sumMerge(pageviews_count_state) AS total, toStartOfDay(e.timestamp) AS day_start FROM web_stats_combined GROUP BY day_start)"""
        assert query == expected

    def test_unsupported_table(self):
        original_query = "select count(), uniq(person_id) from not_events where equals(event, '$pageview')"
        query = self._parse_and_transform(original_query)
        # Query is preserved - wrong table
        expected = self._normalize(original_query)
        assert query == expected

    def test_alias_intact(self):
        original_query = "select count() as c, uniq(person_id) as p, uniq($session_id) as s, properties.utm_medium as m from events where event = '$pageview' group by m"
        query = self._parse_and_transform(original_query)
        expected = """sql(SELECT sumMerge(pageviews_count_state) AS c, uniqMerge(persons_uniq_state) AS p, uniqMerge(sessions_uniq_state) AS s, utm_medium AS m FROM web_stats_combined GROUP BY m)"""
        assert query == expected

    @parameterized.expand(EVENT_PROPERTY_TO_FIELD.items())
    def test_all_event_properties_on_events_supported(self, property_name, field_name):
        original_query = (
            f"select count(), uniq(person_id) from events where event = '$pageview' group by properties.{property_name}"
        )
        query = self._parse_and_transform(original_query)
        expected = f"sql(SELECT sumMerge(pageviews_count_state), uniqMerge(persons_uniq_state) FROM web_stats_combined GROUP BY {field_name})"
        assert query == expected

    @parameterized.expand(SESSION_PROPERTY_TO_FIELD.items())
    def test_all_session_properties_on_events_unsupported(self, property_name, field_name):
        original_query = (
            f"select count(), uniq(person_id) from events where event = '$pageview' group by properties.{property_name}"
        )
        query = self._parse_and_transform(original_query)
        # Query is preserved - no transformation, these are invalid event properties
        assert query == self._normalize(original_query)

    @parameterized.expand(EVENT_PROPERTY_TO_FIELD.items())
    def test_all_event_properties_on_session_unsupported(self, property_name, field_name):
        original_query = (
            f"select count(), uniq(person_id) from events where event = '$pageview' group by session.{property_name}"
        )
        query = self._parse_and_transform(original_query)
        # Query is preserved - no transformation, these are invalid session properties
        assert query == self._normalize(original_query)

    @parameterized.expand(SESSION_PROPERTY_TO_FIELD.items())
    def test_all_session_properties_on_sessions_unsupported(self, property_name, field_name):
        original_query = (
            f"select count(), uniq(person_id) from events where event = '$pageview' group by session.{property_name}"
        )
        query = self._parse_and_transform(original_query)
        expected = f"sql(SELECT sumMerge(pageviews_count_state), uniqMerge(persons_uniq_state) FROM web_stats_combined GROUP BY {field_name})"
        assert query == expected

    def test_all_supported_event_properties_are_in_taxonomy(self):
        for property_name in EVENT_PROPERTY_TO_FIELD.keys():
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
        context = HogQLContext(team_id=self.team.pk)
        transformed = do_preaggregated_table_transforms(node, context)
        assert isinstance(transformed, SelectQuery)

        # Verify that CTEs exist and are transformed correctly
        assert transformed.ctes is not None
        assert len(transformed.ctes) == 3
        assert "pageview_stats" in transformed.ctes
        assert "regular_events" in transformed.ctes
        assert "another_pageview_cte" in transformed.ctes

        # Check that pageview_stats CTE was transformed (should use web_stats_combined)
        pageview_stats_cte = transformed.ctes["pageview_stats"]
        pageview_stats_str = str(pageview_stats_cte.expr)
        assert "web_stats_combined" in pageview_stats_str
        assert "sumMerge(pageviews_count_state)" in pageview_stats_str
        assert "uniqMerge(persons_uniq_state)" in pageview_stats_str

        # Check that regular_events CTE was NOT transformed (should still use events)
        regular_events_cte = transformed.ctes["regular_events"]
        regular_events_str = str(regular_events_cte.expr)
        assert "events" in regular_events_str
        assert "web_stats_combined" not in regular_events_str
        assert "count()" in regular_events_str
        assert "uniq(person_id)" in regular_events_str

        # Check that another_pageview_cte CTE was transformed (should use web_stats_combined)
        another_pageview_cte = transformed.ctes["another_pageview_cte"]
        another_pageview_str = str(another_pageview_cte.expr)
        assert "web_stats_combined" in another_pageview_str
        assert "sumMerge(pageviews_count_state)" in another_pageview_str
        assert "utm_source" in another_pageview_str

        # Check that the main query still references the CTEs correctly
        main_query_str = str(transformed)
        assert "pageview_stats.pageviews" in main_query_str
        assert "regular_events.total_events" in main_query_str
        assert "another_pageview_cte.more_pageviews" in main_query_str
