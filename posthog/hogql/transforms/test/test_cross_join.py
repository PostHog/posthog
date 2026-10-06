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

    @parameterized.expand(
        [
            ("SELECT l.k FROM (SELECT NULL AS k) l CROSS JOIN (SELECT NULL AS k) r WHERE l.k = r.k", True),
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

    @time_machine.travel("2023-02-03", tick=False)
    def test_duplicates_and_merged_people_preserve_results(self) -> None:
        for actor, person_id in [("actor_a", 1), ("actor_a", 1), ("actor_b", 2)]:
            _create_event(
                team=self.team,
                event="example_event",
                distinct_id=actor,
                person_id=UUID(int=person_id),
                timestamp="2023-02-01T00:00:00Z",
            )
        flush_persons_and_events()
        create_person_id_override_by_distinct_id("actor_a", "actor_b", self.team.pk)
        query = """
            SELECT l.distinct_id, r.distinct_id
            FROM events l CROSS JOIN events r
            WHERE l.person_id = r.person_id AND l.event = 'example_event' AND r.event = 'example_event'
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
        assert len(optimized.results) == 9
        assert optimized.clickhouse is not None
        assert "ALL INNER JOIN" in optimized.clickhouse
        self.assertQueryMatchesSnapshot(optimized.clickhouse)
