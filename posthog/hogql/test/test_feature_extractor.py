from typing import cast

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.feature_extractor import HogQLFeatureExtractor, extract_hogql_features
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types


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
        features = extract_hogql_features(parse_select(sql))
        assert features.tables == expected_tables
        assert features.events == expected_events

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
        features = extract_hogql_features(parse_select(sql))
        assert features.events == expected_events

    def test_handles_none_query(self):
        features = extract_hogql_features(None)
        assert features.tables == []
        assert features.events == []

    def test_combined_tables_and_events(self):
        features = extract_hogql_features(
            parse_select(
                "SELECT count() FROM events AS e JOIN persons AS p ON p.id = e.person_id "
                "WHERE e.event = '$ai_generation'"
            )
        )
        assert features.tables == ["events", "persons"]
        assert features.events == ["$ai_generation"]

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

    def _resolve(self, sql: str) -> ast.SelectQuery | ast.SelectSetQuery:
        database = Database.create_for(team=self.team)
        context = HogQLContext(database=database, team_id=self.team.pk, enable_select_queries=True)
        node = parse_select(sql)
        return cast(ast.SelectQuery | ast.SelectSetQuery, resolve_types(node, context, dialect="clickhouse"))

    def test_resolved_ast_uses_type_system(self):
        # After resolution, `event = '$exception'` carries a FieldType pointing
        # at EventsTable; the extractor should pick it up via types just like
        # it does via chain matching.
        features = extract_hogql_features(self._resolve("SELECT * FROM events WHERE event = '$exception'"))
        assert features.events == ["$exception"]

    def test_nested_aliases_on_field_and_constant(self):
        # Aliases can stack — e.g. resolver passes that re-wrap. Verify both
        # the field and the constant unwrap fully so the comparison is still
        # recognised.
        field = ast.Alias(
            alias="outer",
            expr=ast.Alias(alias="inner", expr=ast.Field(chain=["event"])),
        )
        constant = ast.Alias(
            alias="outer",
            expr=ast.Alias(alias="inner", expr=ast.Constant(value="$exception")),
        )
        compare = ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=field, right=constant)

        visitor = HogQLFeatureExtractor()
        visitor.visit(compare)
        assert visitor.events == {"$exception"}

    def test_resolved_event_field_on_non_events_table_ignored(self):
        # Construct a Field whose chain ends in "event" but whose resolved
        # type lives on a non-EventsTable. The chain-only heuristic would
        # accept it; the type-aware path must reject it.
        from posthog.hogql.database.schema.query_log_archive import QueryLogArchiveTable

        non_events_table_type = ast.TableType(table=QueryLogArchiveTable())
        field = ast.Field(
            chain=["query_log", "event"],
            type=ast.FieldType(name="event", table_type=non_events_table_type),
        )
        compare = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=field,
            right=ast.Constant(value="$exception"),
        )

        visitor = HogQLFeatureExtractor()
        visitor.visit(compare)
        assert visitor.events == set()
