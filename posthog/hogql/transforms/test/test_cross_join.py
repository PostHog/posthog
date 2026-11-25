from uuid import UUID

import time_machine
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    create_person_id_override_by_distinct_id,
    flush_persons_and_events,
)

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team


class TestCrossJoinOptimizer(SimpleTestCase):
    @parameterized.expand(
        [
            ("l.distinct_id = r.distinct_id", True),
            ("r.distinct_id = l.distinct_id AND l.timestamp > r.timestamp", True),
            ("l.distinct_id = r.distinct_id AND l.event = r.event", True),
            ("l.distinct_id = r.distinct_id AND r.timestamp > toDateTime('2023-01-01')", True),
            ("l.distinct_id = r.distinct_id OR l.event = 'example'", False),
            ("NOT (l.distinct_id = r.distinct_id)", False),
            ("l.distinct_id = l.event", False),
            ("lower(l.distinct_id) = r.distinct_id", False),
            ("l.distinct_id = r.distinct_id AND rand() > 0", False),
            ("l.distinct_id = r.distinct_id AND l.distinct_id IN (SELECT distinct_id FROM events)", False),
        ]
    )
    def test_compiler_rewrites_only_eligible_equalities(self, predicate: str, rewritten: bool) -> None:
        sql, _ = prepare_and_print_ast(
            parse_select(f"SELECT l.distinct_id FROM events l CROSS JOIN events r WHERE {predicate}"),
            dialect="clickhouse",
            context=HogQLContext(
                team=Team(id=1, timezone="UTC"),
                enable_select_queries=True,
                database=Database(timezone="UTC"),
                restricted_properties=set(),
                use_new_events_schema=False,
                modifiers=HogQLQueryModifiers(optimizeCrossJoins=True),
            ),
        )
        assert ("ALL INNER JOIN" in sql) is rewritten
        assert ("CROSS JOIN" in sql) is not rewritten
        if "l.timestamp" in predicate:
            assert "greater(l.timestamp," in sql.split("WHERE", 1)[1]
        if rewritten:
            right_side = sql.split("ALL INNER JOIN", 1)[1].split(") AS r ON", 1)[0]
            assert right_side.startswith(" (SELECT ")
            assert "equals(r.team_id, 1)" in right_side
            if "r.timestamp >" in predicate:
                assert "greater(r.timestamp," in right_side

    @parameterized.expand(
        [
            ("SELECT l.number, r.number FROM numbers(2) l ALL INNER JOIN numbers(2) r ON l.number = r.number",),
            (
                "SELECT n.number FROM numbers(1) l ALL INNER JOIN events r ON l.number = length(r.event) "
                "RIGHT JOIN numbers(2) n ON l.number = n.number ORDER BY n.number",
            ),
            (
                "SELECT l.event, r.event FROM events l ALL INNER JOIN events r(event, uuid) "
                "ON l.distinct_id = r.distinct_id",
            ),
        ]
    )
    def test_explicit_inner_join_with_table_arguments_or_column_aliases(self, query: str) -> None:
        def compile_query(enabled: bool) -> str:
            sql, _ = prepare_and_print_ast(
                parse_select(query),
                dialect="clickhouse",
                context=HogQLContext(
                    team=Team(id=1, timezone="UTC"),
                    enable_select_queries=True,
                    database=Database(timezone="UTC"),
                    restricted_properties=set(),
                    use_new_events_schema=False,
                    modifiers=HogQLQueryModifiers(optimizeCrossJoins=enabled),
                ),
            )
            return sql

        assert compile_query(True) == compile_query(False)

    @parameterized.expand(
        [
            ("SELECT l.k FROM (SELECT NULL AS k) l CROSS JOIN (SELECT NULL AS k) r WHERE l.k = r.k", True),
            (
                "SELECT l.k FROM (SELECT 1.0 AS k) l CROSS JOIN (SELECT count() AS k FROM events) r WHERE l.k = r.k",
                True,
            ),
            ("SELECT l.distinct_id FROM events l CROSS JOIN events r WHERE l.distinct_id = r.distinct_id", False),
            (
                "SELECT l.distinct_id FROM events l CROSS JOIN events r CROSS JOIN events t WHERE l.distinct_id = r.distinct_id",
                True,
            ),
        ]
    )
    def test_nullable_keys_disabled_modifier_and_join_chains_keep_cross_join(self, query: str, enabled: bool) -> None:
        sql, _ = prepare_and_print_ast(
            parse_select(query),
            dialect="clickhouse",
            context=HogQLContext(
                team=Team(id=1, timezone="UTC"),
                enable_select_queries=True,
                database=Database(timezone="UTC"),
                restricted_properties=set(),
                use_new_events_schema=False,
                modifiers=HogQLQueryModifiers(optimizeCrossJoins=enabled),
            ),
        )
        assert "CROSS JOIN" in sql


class TestCrossJoinResults(ClickhouseTestMixin, BaseTest):
    allow_dual_schema_snapshots = True

    def test_explicit_inner_join_followed_by_right_join_preserves_results(self) -> None:
        query = """
            SELECT n.number FROM numbers(1) l
            ALL INNER JOIN events r ON l.number = length(r.event)
            RIGHT JOIN numbers(2) n ON l.number = n.number
            ORDER BY n.number
        """
        original = execute_hogql_query(query, self.team, modifiers=HogQLQueryModifiers(optimizeCrossJoins=False))
        optimized = execute_hogql_query(query, self.team, modifiers=HogQLQueryModifiers(optimizeCrossJoins=True))
        assert original.results == []
        assert optimized.results == original.results

    @parameterized.expand([("person_id", 9), ("distinct_id", 5)])
    @time_machine.travel("2023-02-03", tick=False)
    def test_duplicates_and_merged_people_preserve_results(self, key: str, expected_rows: int) -> None:
        other_team = Team.objects.create(organization=self.organization)
        for team, actor, person_id in [
            (self.team, "actor_a", 1),
            (self.team, "actor_a", 1),
            (self.team, "actor_b", 2),
            (other_team, "actor_a", 1),
        ]:
            _create_event(
                team=team,
                event="example_event",
                distinct_id=actor,
                person_id=UUID(int=person_id),
                timestamp="2023-02-01T00:00:00Z",
            )
        flush_persons_and_events()
        create_person_id_override_by_distinct_id("actor_a", "actor_b", self.team.pk)
        query = f"""
            SELECT l.distinct_id, r.distinct_id
            FROM events l CROSS JOIN events r
            WHERE l.{key} = r.{key} AND l.event = 'example_event' AND r.event = 'example_event'
            AND l.timestamp >= r.timestamp
            AND r.timestamp >= toDateTime('2023-02-01') AND r.timestamp < toDateTime('2023-02-02')
            ORDER BY l.distinct_id, r.distinct_id
        """
        original = execute_hogql_query(
            query,
            self.team,
            modifiers=HogQLQueryModifiers(
                optimizeCrossJoins=False,
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
            ),
        )
        optimized = execute_hogql_query(
            query,
            self.team,
            modifiers=HogQLQueryModifiers(
                optimizeCrossJoins=True, personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )
        assert optimized.results == original.results
        assert len(optimized.results) == expected_rows
        assert optimized.clickhouse is not None
        assert "ALL INNER JOIN" in optimized.clickhouse
        self.assertQueryMatchesSnapshot(optimized.clickhouse)
