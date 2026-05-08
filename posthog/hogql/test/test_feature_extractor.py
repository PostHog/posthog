from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.feature_extractor import HogQLFeatureExtractor, extract_hogql_features
from posthog.hogql.parser import parse_select


class TestHogQLFeatureExtractor(BaseTest):
    @parameterized.expand(
        [
            ("simple_events_select", "SELECT count() FROM events", ["events"], []),
            ("aliased_events_table", "SELECT * FROM events AS e LIMIT 10", ["events"], []),
            ("session_replay_table", "SELECT session_id FROM session_replay_events", ["session_replay_events"], []),
            (
                "join_persons_and_events",
                "SELECT * FROM events AS e JOIN persons AS p ON p.id = e.person_id",
                ["events", "persons"],
                [],
            ),
            ("subquery_inner_join", "SELECT * FROM (SELECT * FROM events) AS sub", ["events"], []),
        ]
    )
    def test_extracts_table_references(self, _name, sql, expected_tables, expected_events):
        tables, events = extract_hogql_features(parse_select(sql))
        assert tables == expected_tables
        assert events == expected_events

    @parameterized.expand(
        [
            ("ai_generation_eq", "SELECT * FROM events WHERE event = '$ai_generation'", ["$ai_generation"]),
            ("exception_eq", "SELECT * FROM events WHERE event = '$exception'", ["$exception"]),
            ("web_vitals_eq", "SELECT * FROM events WHERE event = '$web_vitals'", ["$web_vitals"]),
            (
                "feature_flag_called_eq",
                "SELECT * FROM events WHERE event = '$feature_flag_called'",
                ["$feature_flag_called"],
            ),
            (
                "in_clause_multiple_ai",
                "SELECT * FROM events WHERE event IN ('$ai_generation', '$ai_span')",
                ["$ai_generation", "$ai_span"],
            ),
            (
                "constant_on_left",
                "SELECT * FROM events WHERE '$exception' = event",
                ["$exception"],
            ),
            (
                "aliased_event_field",
                "SELECT * FROM events AS e WHERE e.event = '$ai_generation'",
                ["$ai_generation"],
            ),
            (
                "uninteresting_event_dropped",
                "SELECT * FROM events WHERE event = 'pageview' OR event = '$ai_generation'",
                ["$ai_generation"],
            ),
            ("unknown_event_dropped", "SELECT * FROM events WHERE event = 'random_event'", []),
        ]
    )
    def test_extracts_event_filters(self, _name, sql, expected_events):
        _tables, events = extract_hogql_features(parse_select(sql))
        assert events == expected_events

    def test_handles_none_query(self):
        tables, events = extract_hogql_features(None)
        assert tables == []
        assert events == []

    def test_combined_tables_and_events(self):
        tables, events = extract_hogql_features(
            parse_select(
                "SELECT count() FROM events AS e JOIN persons AS p ON p.id = e.person_id "
                "WHERE e.event = '$ai_generation'"
            )
        )
        assert tables == ["events", "persons"]
        assert events == ["$ai_generation"]

    def test_visitor_dedups(self):
        visitor = HogQLFeatureExtractor()
        visitor.visit(
            parse_select(
                "SELECT * FROM events WHERE event = '$exception' "
                "UNION ALL SELECT * FROM events WHERE event = '$exception'"
            )
        )
        assert visitor.tables == {"events"}
        assert visitor.events == {"$exception"}
