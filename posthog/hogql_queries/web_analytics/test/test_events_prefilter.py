from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql_queries.web_analytics.events_prefilter import EventsPrefilterTransformer


class TestEventsPrefilterTransformer(BaseTest):
    def _make_transformer(self) -> EventsPrefilterTransformer:
        return EventsPrefilterTransformer(
            team_id=1,
            date_from="2024-01-01",
            date_to="2024-01-31",
        )

    def test_wraps_all_from_events(self):
        sql = """
SELECT * FROM (
    SELECT * FROM events WHERE team_id = 1
) AS counts
LEFT JOIN (
    SELECT * FROM events WHERE team_id = 1
) AS bounce ON 1=1
"""
        transformer = self._make_transformer()
        result = transformer.transform(sql)

        assert result.count("SELECT * FROM events WHERE events.team_id = 1 AND toDate") == 2
        assert "counts" in result
        assert "bounce" in result

    def test_wraps_single_from_events(self):
        sql = "SELECT * FROM events WHERE team_id = 1"
        transformer = self._make_transformer()
        result = transformer.transform(sql)

        assert "SELECT * FROM events WHERE events.team_id = 1 AND toDate" in result

    def test_no_change_for_no_from_events(self):
        sql = "SELECT 1 FROM numbers(10)"
        transformer = self._make_transformer()
        result = transformer.transform(sql)

        assert result == sql

    def test_wraps_all_three_from_events(self):
        sql = """
SELECT * FROM (SELECT * FROM events) AS counts
LEFT JOIN (SELECT * FROM events) AS bounce ON 1=1
LEFT JOIN (SELECT * FROM events) AS time_on_page ON 1=1
"""
        transformer = self._make_transformer()
        result = transformer.transform(sql)

        assert result.count("SELECT * FROM events WHERE events.team_id") == 3

    def test_prefilter_clause_contains_date_bounds(self):
        transformer = EventsPrefilterTransformer(
            team_id=42,
            date_from="2024-03-15",
            date_to="2024-04-15",
        )
        clause = transformer.prefilter_clause

        assert "events.team_id = 42" in clause
        assert "toDate(events.timestamp) >= '2024-03-15'" in clause
        assert "toDate(events.timestamp) <= '2024-04-15'" in clause

    @parameterized.expand(
        [
            ("insights_query", "SELECT count() FROM other_table WHERE team_id = 1 GROUP BY event"),
            ("no_events_table", "SELECT 1 FROM sessions WHERE session_id = 'abc'"),
            ("empty_string", ""),
        ],
    )
    def test_queries_without_from_events_unaffected(self, _name, sql):
        transformer = self._make_transformer()
        result = transformer.transform(sql)

        assert result == sql

    def test_case_insensitive_from_matching(self):
        sql = """
SELECT * FROM (SELECT * from events WHERE 1) AS counts
LEFT JOIN (SELECT * from events WHERE 1) AS bounce ON 1=1
"""
        transformer = self._make_transformer()
        result = transformer.transform(sql)

        assert result.count("SELECT * FROM events WHERE events.team_id") == 2

    def test_does_not_match_events_as_substring(self):
        sql = """
SELECT * FROM (SELECT * FROM events_backup WHERE 1) AS other
"""
        transformer = self._make_transformer()
        result = transformer.transform(sql)

        assert "events_backup" in result
        assert "SELECT * FROM events WHERE events.team_id" not in result
