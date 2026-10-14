import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.events_json import EVENTS_JSON_DATA_TABLE
from posthog.models.event.util import create_event

PERSON_A = "01960000-0000-7000-8000-000000000001"
PERSON_B = "01960000-0000-7000-8000-000000000002"


class TestEventsPersonIdPrefilter(BaseTest):
    def _print(
        self,
        query: str,
        enabled: bool | None = False,
        mode: PersonsOnEventsMode = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
        new_events_schema: bool = False,
    ) -> tuple[str, dict[str, object]]:
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            modifiers=HogQLQueryModifiers(
                personIdFilterPrewhere=enabled,
                personsOnEventsMode=mode,
                useNewEventsSchema=new_events_schema,
                pushDownPredicates=False,
            ),
        )
        sql, _ = prepare_and_print_ast(parse_select(query), context, "clickhouse")
        return sql, dict(context.values)

    @parameterized.expand(
        [
            ("unqualified_equality", "events", "", f"= '{PERSON_A}'", False),
            ("bare_equality", "events", "events", f"= '{PERSON_A}'", False),
            ("aliased_equality", "events AS e", "e", f"= '{PERSON_A}'", True),
            ("aliased_list", "events AS e", "e", f"IN ('{PERSON_A}', '{PERSON_B}')", False),
        ]
    )
    def test_compiles_the_complete_candidate_filter(
        self, _name: str, source: str, alias: str, person_filter: str, new_events_schema: bool
    ) -> None:
        prefix = f"{alias}." if alias else ""
        time_filter = f"{prefix}timestamp >= now() - INTERVAL 7 DAY AND {prefix}timestamp < now()"
        where = f"{prefix}person_id {person_filter} AND {time_filter}"
        query = f"SELECT {prefix}uuid FROM {source} WHERE {where}"
        expected = (
            f"SELECT {prefix}uuid FROM {source} PREWHERE {prefix}team_id = {self.team.pk} "
            f"AND {time_filter} AND ({prefix}event_person_id {person_filter} OR {prefix}distinct_id IN "
            f"(SELECT distinct_id FROM raw_person_distinct_id_overrides WHERE person_id {person_filter})) "
            f"WHERE {where}"
        )

        assert self._print(query, True, new_events_schema=new_events_schema) == self._print(
            expected, new_events_schema=new_events_schema
        )

    @parameterized.expand([None, False])
    def test_requires_an_explicit_opt_in(self, enabled: bool | None) -> None:
        query = f"SELECT uuid FROM events WHERE person_id = '{PERSON_A}'"
        assert self._print(query, enabled) == self._print(query, False)

    @parameterized.expand(
        [
            ("or", f"SELECT uuid FROM events WHERE person_id = '{PERSON_A}' OR event = 'sample'"),
            ("not_equal", f"SELECT uuid FROM events WHERE person_id != '{PERSON_A}'"),
            ("not_in", f"SELECT uuid FROM events WHERE person_id NOT IN ('{PERSON_A}')"),
            ("computed_person", f"SELECT uuid FROM events WHERE toString(person_id) = '{PERSON_A}'"),
            ("subquery_ids", "SELECT uuid FROM events WHERE person_id IN (SELECT id FROM persons)"),
            ("other_table", f"SELECT id FROM persons WHERE id = '{PERSON_A}'"),
            (
                "alias_shadowing",
                f"SELECT event AS person_id FROM events WHERE person_id = '{PERSON_A}'",
            ),
            (
                "self_join",
                f"SELECT a.uuid FROM events a JOIN events b ON a.uuid = b.uuid WHERE b.person_id = '{PERSON_A}'",
            ),
            (
                "existing_prewhere",
                f"SELECT uuid FROM events PREWHERE event = 'sample' WHERE person_id = '{PERSON_A}'",
            ),
            (
                "cte",
                f"WITH selected AS (SELECT uuid FROM events WHERE person_id = '{PERSON_A}') SELECT uuid FROM selected",
            ),
            (
                "nested_query",
                f"SELECT uuid FROM (SELECT uuid FROM events WHERE person_id = '{PERSON_A}')",
            ),
            (
                "array_join_clause",
                f"SELECT uuid FROM events ARRAY JOIN [1, 2] AS item WHERE person_id = '{PERSON_A}'",
            ),
            (
                "array_join_call",
                f"SELECT uuid, arrayJoin([1, 2]) FROM events WHERE person_id = '{PERSON_A}'",
            ),
            (
                "block_row_number",
                f"SELECT uuid FROM events WHERE person_id = '{PERSON_A}' AND rowNumberInAllBlocks() % 2 = 0",
            ),
            (
                "block_row_number_alias",
                f"SELECT rowNumberInBlock() AS row_num, uuid FROM events WHERE person_id = '{PERSON_A}' AND row_num = 0",
            ),
            (
                "block_time",
                f"SELECT nowInBlock('UTC'), uuid FROM events WHERE person_id = '{PERSON_A}'",
            ),
            (
                "random",
                f"SELECT uuid FROM events WHERE person_id = '{PERSON_A}' AND RAND() % 2 = 0",
            ),
        ]
    )
    def test_unsupported_shapes_compile_unchanged(self, _name: str, query: str) -> None:
        assert self._print(query, True) == self._print(query)

    @parameterized.expand(
        [PersonsOnEventsMode.DISABLED, PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS]
    )
    def test_other_identity_modes_compile_unchanged(self, mode: PersonsOnEventsMode) -> None:
        query = f"SELECT uuid FROM events WHERE person_id = '{PERSON_A}'"
        assert self._print(query, True, mode=mode) == self._print(query, mode=mode)

    def test_large_person_list_compiles_unchanged(self) -> None:
        ids = ", ".join(f"'{UUID(int=index + 1)}'" for index in range(101))
        query = f"SELECT uuid FROM events WHERE person_id IN ({ids})"
        assert self._print(query, True) == self._print(query)

    @parameterized.expand(["distinct_id", "event_person_id", "events"])
    def test_select_aliases_do_not_capture_generated_columns(self, alias: str) -> None:
        query = f"SELECT event AS {alias}, uuid FROM events WHERE person_id = '{PERSON_A}'"
        expected = (
            f"SELECT event AS {alias}, uuid FROM events PREWHERE events.team_id = {self.team.pk} "
            f"AND (events.event_person_id = '{PERSON_A}' OR events.distinct_id IN "
            f"(SELECT distinct_id FROM raw_person_distinct_id_overrides WHERE person_id = '{PERSON_A}')) "
            f"WHERE person_id = '{PERSON_A}'"
        )
        assert self._print(query, True) == self._print(expected)


class TestEventsPersonIdPrefilterIdentity(ClickhouseTestMixin, BaseTest):
    def _record_event(
        self, event: str, distinct_id: str, person_id: str, payload: str, *, new_events_schema: bool
    ) -> None:
        if new_events_schema:
            sync_execute(
                f"INSERT INTO {EVENTS_JSON_DATA_TABLE} "
                "(uuid, event, team_id, distinct_id, person_id, timestamp, properties) "
                "SELECT toUUID(%(uuid)s), %(event)s, %(team_id)s, %(distinct_id)s, toUUID(%(person_id)s), "
                "toDateTime64('2026-09-01 12:00:00', 6, 'UTC'), CAST(%(properties)s AS JSON)",
                {
                    "uuid": str(uuid4()),
                    "event": event,
                    "team_id": self.team.pk,
                    "distinct_id": distinct_id,
                    "person_id": person_id,
                    "properties": json.dumps({"payload": payload}),
                },
            )
        else:
            with self.settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=False):
                create_event(
                    team=self.team,
                    event_uuid=uuid4(),
                    event=event,
                    distinct_id=distinct_id,
                    person_id=UUID(person_id),
                    timestamp=datetime(2026, 9, 1, 12, tzinfo=UTC),
                    properties={"payload": payload},
                )

    @parameterized.expand(
        [
            ("properties_on_events_legacy", PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS, False),
            ("properties_on_events_json", PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS, True),
            ("properties_joined_legacy", PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED, False),
            ("properties_joined_json", PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED, True),
            ("predicate_pushdown", PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS, False, True),
        ]
    )
    def test_keeps_stored_merged_reassigned_and_deleted_ownership(
        self,
        _name: str,
        mode: PersonsOnEventsMode,
        new_events_schema: bool,
        push_down_predicates: bool = False,
    ) -> None:
        owners = [
            ("stored", PERSON_A),
            ("merged", PERSON_B),
            ("reassigned", PERSON_A),
            ("deleted", PERSON_A),
            ("reused", PERSON_A),
            ("reused", PERSON_B),
        ]
        for index, (distinct_id, person_id) in enumerate(owners):
            self._record_event(
                f"event-{index}", distinct_id, person_id, f"value-{index}", new_events_schema=new_events_schema
            )
        sync_execute(
            "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version, is_deleted) VALUES",
            [
                (self.team.pk, "merged", PERSON_A, 1, 0),
                (self.team.pk, "reassigned", PERSON_A, 1, 0),
                (self.team.pk, "reassigned", PERSON_B, 2, 0),
                (self.team.pk, "deleted", PERSON_B, 1, 0),
                (self.team.pk, "deleted", PERSON_B, 2, 1),
            ],
        )
        where = f"person_id = '{PERSON_A}' AND timestamp >= '2026-09-01' AND timestamp < '2026-09-02'"
        query = f"SELECT event, properties.payload FROM events WHERE {where} ORDER BY event"
        modifiers = HogQLQueryModifiers(
            personsOnEventsMode=mode,
            useNewEventsSchema=new_events_schema,
            pushDownPredicates=push_down_predicates,
        )

        def assert_results(expected_indices: list[int]) -> None:
            modifiers.personIdFilterPrewhere = False
            baseline = execute_hogql_query(query, team=self.team, modifiers=modifiers)
            modifiers.personIdFilterPrewhere = True
            optimized = execute_hogql_query(query, team=self.team, modifiers=modifiers)

            assert optimized.results == baseline.results == [(f"event-{i}", f"value-{i}") for i in expected_indices]
            assert optimized.clickhouse is not None
            assert "PREWHERE" in optimized.clickhouse

            aggregate_query = f"SELECT count(), sum(length(properties.payload)) FROM events WHERE {where}"
            modifiers.personIdFilterPrewhere = False
            baseline_aggregate = execute_hogql_query(aggregate_query, team=self.team, modifiers=modifiers)
            modifiers.personIdFilterPrewhere = True
            optimized_aggregate = execute_hogql_query(aggregate_query, team=self.team, modifiers=modifiers)

            assert (
                optimized_aggregate.results
                == baseline_aggregate.results
                == [(len(expected_indices), 7 * len(expected_indices))]
            )

        assert_results([0, 1, 3, 4])

        sync_execute(
            "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version, is_deleted) VALUES",
            [
                (self.team.pk, "merged", PERSON_B, 2, 0),
                (self.team.pk, "reassigned", PERSON_A, 3, 0),
                (self.team.pk, "deleted", PERSON_B, 3, 0),
                (self.team.pk, "reused", PERSON_A, 1, 0),
            ],
        )
        self._record_event("event-6", "reassigned", PERSON_B, "value-6", new_events_schema=new_events_schema)
        assert_results([0, 2, 4, 5, 6])

        sync_execute(
            "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version, is_deleted) VALUES",
            [
                (self.team.pk, "merged", PERSON_A, 3, 0),
                (self.team.pk, "reassigned", PERSON_A, 4, 1),
                (self.team.pk, "deleted", PERSON_B, 4, 1),
                (self.team.pk, "reused", PERSON_A, 2, 1),
                (self.team.pk, "merged", PERSON_B, 2, 0),
            ],
        )
        assert_results([0, 1, 2, 3, 4])

        sync_execute("OPTIMIZE TABLE person_distinct_id_overrides FINAL")
        assert_results([0, 1, 2, 3, 4])

    def test_does_not_limit_distinct_id_candidates(self) -> None:
        distinct_ids = [f"historical-{index:04d}" for index in range(2501)]
        sync_execute(
            "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version, is_deleted) VALUES",
            [(self.team.pk, distinct_id, PERSON_A, 1, 0) for distinct_id in distinct_ids],
        )
        self._record_event("last-candidate", distinct_ids[-1], PERSON_B, "last", new_events_schema=False)
        response = execute_hogql_query(
            f"SELECT event FROM events WHERE person_id = '{PERSON_A}' ORDER BY event LIMIT 1",
            team=self.team,
            modifiers=HogQLQueryModifiers(
                personIdFilterPrewhere=True,
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                useNewEventsSchema=False,
                pushDownPredicates=False,
            ),
        )

        assert response.results == [("last-candidate",)]
        assert response.clickhouse is not None
        assert "PREWHERE" in response.clickhouse
