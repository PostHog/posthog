import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_flag_evaluations,
    _create_person,
    cleanup_materialized_columns,
    flush_persons_and_events,
)
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import param, parameterized

from posthog.schema import HogQLQueryModifiers, MaterializationMode, PersonsOnEventsMode

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DatabaseField, FieldTraverser, LazyJoin, StringJSONDatabaseField, VirtualTable
from posthog.hogql.database.schema.util.where_clause_extractor import is_nondeterministic_function
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.mapping import HOGQL_CLICKHOUSE_FUNCTIONS
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import HogQLQueryExecutor, execute_hogql_query
from posthog.hogql.transforms.flag_calls_union import rename_flag_call_scans_to_union
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.escape import substitute_params
from posthog.constants import AvailableFeature
from posthog.test.persons import create_group_type_mapping

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

from ee.clickhouse.materialized_columns.columns import materialize

MIXED = "event IN ('$pageview', '$feature_flag_called')"
SESSION_ID = "0190a8d1-3f7a-7b00-8000-000000000001"
E_MIXED = "e.event IN ('$pageview', '$feature_flag_called')"
UNION = "posthog.events_with_flag_calls"
READ = FlagEvaluationsMode.READ_FLAG_EVALUATIONS
ONLY = FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY


class _TableCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[str] = []

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field):
            self.tables.append(".".join(str(part) for part in node.table.chain))
        super().visit_join_expr(node)


def _select(query: str | ast.SelectQuery) -> ast.SelectQuery:
    return cast(ast.SelectQuery, parse_select(query) if isinstance(query, str) else clone_expr(query))


def _global_join(query: str) -> ast.SelectQuery:
    # HogQL has no GLOBAL syntax. The recordings list builds a GLOBAL join in its AST.
    select = _select(query)
    assert select.select_from is not None and select.select_from.next_join is not None
    select.select_from.next_join.join_type = "GLOBAL INNER JOIN"
    return select


def _set_mode(organization, mode: FlagEvaluationsMode) -> None:
    OrganizationFeatureFlagsConfig.objects.update_or_create(
        organization=organization, defaults={"flag_evaluations_mode": mode}
    )


def _enabled_flags(union: bool):
    enabled = {"hogql-flag-calls-from-flag-evaluations", *(["hogql-flag-calls-union"] if union else [])}
    return patch(
        "posthog.hogql.database.database.feature_enabled_or_false",
        side_effect=lambda key, *args, **kwargs: key in enabled,
    )


def _restrict(organization, team, name: str) -> None:
    organization.available_product_features = [
        {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
    ]
    organization.save()
    definition = PropertyDefinition.objects.create(
        team=team, name=name, property_type="String", type=PropertyDefinition.Type.EVENT
    )
    PropertyAccessControl.objects.create(
        team=team, property_definition=definition, access_level=PropertyAccessLevel.NONE.value
    )


class TestRenameFlagCallScansToUnion(SimpleTestCase):
    @parameterized.expand(
        [
            ("event_in_a_list_with_other_events", f"SELECT count() FROM events WHERE {MIXED}", [UNION], []),
            ("paths_v2_step_sources", f"SELECT e.event FROM events AS e WHERE {E_MIXED}", [UNION], []),
            (
                "funnel_step_column",
                "SELECT if(event = '$feature_flag_called' AND properties.$feature_flag = 'f', 1, 0) AS step_1 "
                "FROM events",
                [UNION],
                [],
            ),
            (
                "or_of_event_comparisons",
                "SELECT count() FROM events WHERE event = '$pageview' OR equals(event, '$feature_flag_called')",
                [UNION],
                [],
            ),
            # The flag_evaluations swap handles this scan. Events holds every flag call on mode 1. The swap swaps or
            # refuses the scan on mode 2.
            ("only_flag_calls", "SELECT count() FROM events WHERE event = '$feature_flag_called'", ["events"], []),
            (
                "only_flag_calls_with_sample",
                "SELECT count() FROM events SAMPLE 0.1 WHERE event = '$feature_flag_called'",
                ["events"],
                [],
            ),
            (
                "left_join_after_the_scan",
                f"SELECT count() FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED}",
                [UNION, "persons"],
                [],
            ),
            (
                "left_join_with_an_unqualified_event",
                f"SELECT count() FROM events LEFT JOIN persons AS p ON events.person_id = p.id WHERE {MIXED}",
                [UNION, "persons"],
                [],
            ),
            (
                "left_join_with_an_unqualified_event_aliased_to_itself",
                "SELECT event AS event, count() FROM events LEFT JOIN persons AS p ON events.person_id = p.id "
                f"WHERE {MIXED} GROUP BY event",
                [UNION, "persons"],
                [],
            ),
            (
                "only_flag_calls_with_a_join_and_an_unqualified_event",
                "SELECT count() FROM events LEFT JOIN persons AS p ON events.person_id = p.id "
                "WHERE event = '$feature_flag_called'",
                ["events", "persons"],
                [],
            ),
            (
                "array_join_with_an_unqualified_event",
                f"SELECT count() FROM events ARRAY JOIN [1, 2] AS x WHERE {MIXED}",
                [UNION],
                [],
            ),
            (
                "inner_join_after_the_scan",
                f"SELECT count() FROM events AS e INNER JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED}",
                [UNION, "persons"],
                [],
            ),
            (
                "global_join_after_the_scan",
                _global_join(
                    f"SELECT count() FROM events AS e INNER JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED}"
                ),
                [UNION, "persons"],
                [],
            ),
            ("sample_one", f"SELECT count() FROM events SAMPLE 1 WHERE {MIXED}", [UNION], []),
            ("scan_in_a_subquery", f"SELECT count() FROM (SELECT event FROM events WHERE {MIXED})", [UNION], []),
            (
                "comparison_only_in_a_subquery",
                f"SELECT count() FROM events WHERE distinct_id IN (SELECT distinct_id FROM events WHERE {MIXED})",
                ["events", UNION],
                [],
            ),
            (
                "no_flag_call_comparison",
                "SELECT count() FROM events SAMPLE 0.1 WHERE event = '$pageview'",
                ["events"],
                [],
            ),
            ("not_equals", "SELECT count() FROM events WHERE event != '$feature_flag_called'", ["events"], []),
            (
                "constant_on_another_column",
                "SELECT count() FROM events WHERE distinct_id = '$feature_flag_called'",
                ["events"],
                [],
            ),
            (
                "scan_after_another_table",
                f"SELECT count() FROM persons AS p JOIN events AS e ON p.id = e.person_id WHERE {E_MIXED}",
                ["persons", "events"],
                ["it joins events after another table"],
            ),
            (
                "scan_of_only_flag_calls_after_another_table",
                "SELECT count() FROM persons AS p JOIN events AS e ON p.id = e.person_id "
                "WHERE e.event = '$feature_flag_called'",
                ["persons", "events"],
                ["it joins events after another table"],
            ),
            (
                "right_join_after_the_scan",
                f"SELECT count() FROM events AS e RIGHT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED}",
                ["events", "persons"],
                ["it joins another table to events with RIGHT JOIN"],
            ),
            (
                "final",
                f"SELECT count() FROM events FINAL WHERE {MIXED}",
                ["events"],
                ["it uses FINAL or table arguments on events"],
            ),
            (
                "column_aliases",
                f"SELECT count() FROM events AS e (uuid, event, properties, timestamp, distinct_id, x) WHERE {E_MIXED}",
                ["events"],
                ["it names the events columns with column aliases"],
            ),
            ("sample_ratio", f"SELECT count() FROM events SAMPLE 0.1 WHERE {MIXED}", ["events"], ["it uses SAMPLE"]),
            ("select_star", f"SELECT * FROM events WHERE {MIXED}", ["events"], ["it selects * or COLUMNS(...)"]),
            (
                "cte_named_events",
                f"WITH events AS (SELECT '$pageview' AS event) SELECT count() FROM events WHERE {MIXED}",
                ["events"],
                [],
            ),
        ]
    )
    def test_renames_the_scans_the_union_reads_and_names_why_it_cannot_read_the_rest(
        self,
        _name: str,
        query: str | ast.SelectQuery,
        expected_tables: list[str],
        expected_refusals: list[str],
        only_in_flag_evaluations: bool = True,
    ):
        select = _select(query)
        rename = rename_flag_call_scans_to_union(
            select, flag_key_compares_as_string=lambda: True, only_in_flag_evaluations=only_in_flag_evaluations
        )
        collector = _TableCollector()
        collector.visit(select)

        assert collector.tables == expected_tables
        assert list(rename.refusals) == expected_refusals

    def test_row_dependent_functions_cover_every_hogql_function_in_their_families(self):
        families = re.compile(
            r"^(rand|random|rowNumber|blockNumber|nowInBlock|generateUUID|generateULID|runningDifference|neighbor)"
        )

        assert [
            name
            for name in HOGQL_CLICKHOUSE_FUNCTIONS
            if families.match(name) and not is_nondeterministic_function(name)
        ] == []


class TestReadFlagCallsWithUnion(BaseTest):
    def _sql(
        self,
        query: str | ast.SelectQuery,
        *,
        mode: FlagEvaluationsMode = READ,
        union: bool = True,
        persons_on_events: PersonsOnEventsMode | None = None,
        new_events_schema: bool | None = None,
        modifiers: HogQLQueryModifiers | None = None,
    ) -> str:
        _set_mode(self.organization, mode)
        with _enabled_flags(union=union):
            sql, context = HogQLQueryExecutor(
                query=query,
                team=self.team,
                modifiers=(modifiers or HogQLQueryModifiers()).model_copy(
                    update={
                        "personsOnEventsMode": persons_on_events,
                        "useNewEventsSchema": _events_schema_for(mode, new_events_schema),
                    },
                ),
                pretty=False,
            ).generate_clickhouse_sql()
        return substitute_params(sql, context.values)

    @staticmethod
    def _branches(sql: str) -> list[str]:
        start = sql.index("UNION ALL")
        union_start = sql.rindex("(SELECT", 0, sql.rindex("FROM events", 0, start))
        union_end = sql.index(") AS ", sql.rindex("FROM flag_evaluations"))
        return sql[union_start:union_end].split("UNION ALL")

    @parameterized.expand(
        [
            ("mixed_query", f"SELECT count() FROM events WHERE {MIXED}", True, True),
            ("mixed_query_with_the_flag_off", f"SELECT count() FROM events WHERE {MIXED}", False, False),
            (
                "query_phase_1_swaps",
                "SELECT count() FROM events WHERE event = '$feature_flag_called' "
                "AND properties.$feature_flag = 'f' AND timestamp >= now() - INTERVAL 7 DAY",
                True,
                False,
            ),
            # The CTE shadows events, so the query reads the CTE on every mode.
            (
                "cte_named_events",
                f"WITH events AS (SELECT '$pageview' AS event) SELECT count() FROM events WHERE {MIXED}",
                True,
                False,
            ),
            # Each branch reads the raw string of a property without a type, as events does.
            (
                "string_parser_on_an_untyped_property",
                f"SELECT toFloatOrZero(properties.probe) FROM events WHERE {MIXED}",
                True,
                True,
            ),
            param(
                "cte_named_events_on_mode_2",
                f"WITH events AS (SELECT '$pageview' AS event) SELECT count() FROM events WHERE {MIXED}",
                True,
                False,
                mode=ONLY,
            ),
            # Mode 1 keeps a materialized property on events, so mode 2 shows which columns the union can read.
            param(
                "property_in_a_string_materialized_column_on_mode_2",
                f"SELECT properties.probe FROM events WHERE {MIXED}",
                True,
                True,
                mode=ONLY,
                column_type="Nullable(String)",
            ),
            # Each branch reads the property from JSON, so the typed column never reaches the UNION ALL.
            param(
                "typed_materialized_column_on_the_native_events_schema_on_mode_2",
                f"SELECT properties.probe FROM events WHERE {MIXED}",
                True,
                True,
                mode=ONLY,
                column_type="Nullable(Float64)",
                new_events_schema=True,
            ),
            param(
                "typed_materialized_column_with_materialization_disabled",
                f"SELECT properties.probe FROM events WHERE {MIXED}",
                True,
                True,
                column_type="Nullable(Float64)",
                modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.DISABLED),
            ),
        ]
    )
    def test_union_reads_the_scans_phase_1_leaves_on_events(
        self,
        _name: str,
        query: str,
        union: bool,
        expected_union: bool,
        mode: FlagEvaluationsMode = READ,
        column_type: str | None = None,
        new_events_schema: bool | None = None,
        modifiers: HogQLQueryModifiers | None = None,
    ):
        if column_type is not None:
            self.addCleanup(cleanup_materialized_columns)
            materialize("events", "probe", is_nullable=True, column_type=column_type)
        sql = self._sql(query, union=union, mode=mode, new_events_schema=new_events_schema, modifiers=modifiers)

        assert ("UNION ALL" in sql) is expected_union
        if expected_union:
            assert re.search(r"FROM flag_evaluations\b", sql) is not None

    @parameterized.expand(
        [
            (
                "right_join",
                f"SELECT count() FROM events AS e RIGHT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED}",
                "RIGHT JOIN",
            ),
            (
                "field_flag_evaluations_lacks",
                f"SELECT goe_0.properties.plan FROM events WHERE {MIXED}",
                "goe_0.properties",
            ),
            param(
                "join_whose_on_clause_reads_another_field",
                f"SELECT probe_join.key FROM events WHERE {MIXED}",
                "probe_join",
                warehouse_join=True,
            ),
            # Each branch projects the raw value. The flag_evaluations branch has no Float64 column to match this one.
            param(
                "property_in_a_typed_materialized_column",
                f"SELECT properties.probe FROM events WHERE {MIXED}",
                "probe, which events stores in a Nullable\\(Float64\\) column",
                typed_column=True,
            ),
        ]
    )
    def test_mode_1_reads_events_and_mode_2_raises_when_the_union_cannot_read_a_mixed_scan(
        self,
        _name: str,
        query: str,
        reason: str,
        warehouse_join: bool = False,
        typed_column: bool = False,
    ):
        if typed_column:
            self.addCleanup(cleanup_materialized_columns)
            materialize("events", "probe", is_nullable=True, column_type="Nullable(Float64)")
        if warehouse_join:
            # Joined on persons, it reaches events as a join that compares `person.properties.email`, not its key.
            DataWarehouseJoin.objects.create(
                team=self.team,
                source_table_name="persons",
                source_table_key="properties.email",
                joining_table_name="groups",
                joining_table_key="key",
                field_name="probe_join",
            )
        persons_on_events = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS

        # The native events schema reads every property from JSON, so only the legacy schema reads a typed column.
        new_events_schema = False if typed_column else None
        assert "UNION ALL" not in self._sql(
            query, persons_on_events=persons_on_events, new_events_schema=new_events_schema
        )
        with pytest.raises(QueryError, match=reason):
            self._sql(query, mode=ONLY, persons_on_events=persons_on_events, new_events_schema=new_events_schema)

    @parameterized.expand([("dotted", UNION), ("quoted", f"`{UNION}`")])
    def test_query_cannot_name_the_union_table(self, _name: str, table: str):
        with pytest.raises(QueryError, match="Unknown table `posthog.events_with_flag_calls`"):
            self._sql(f"SELECT count() FROM {table}")

    def test_in_subquery_over_the_union_runs_once_with_global_in(self):
        sql = self._sql(
            f"SELECT count() FROM events WHERE distinct_id IN (SELECT distinct_id FROM events WHERE {MIXED})"
        )

        assert "globalIn(events.distinct_id" in sql

    @parameterized.expand(
        [
            ("restricted_on_mode_1", READ, None, False, False),
            # Mode 2 reads every flag call from flag_evaluations, so it never asks events for the flag key.
            ("restricted_on_mode_2", ONLY, None, False, True),
            ("boolean_on_native_json_on_mode_1", READ, "Boolean", True, False),
            ("numeric_on_native_json_on_mode_1", READ, "Numeric", True, False),
            ("boolean_on_native_json_on_mode_2", ONLY, "Boolean", True, True),
        ]
    )
    def test_flag_key_that_events_cannot_read_raw_keeps_mode_1_on_events(
        self, _name: str, mode: FlagEvaluationsMode, flag_key_type: str | None, new_events_schema: bool, expected: bool
    ):
        if flag_key_type is None:
            _restrict(self.organization, self.team, "$feature_flag")
        else:
            PropertyDefinition.objects.create(
                team=self.team, name="$feature_flag", property_type=flag_key_type, type=PropertyDefinition.Type.EVENT
            )

        sql = self._sql(f"SELECT count() FROM events WHERE {MIXED}", mode=mode, new_events_schema=new_events_schema)

        assert ("UNION ALL" in sql) is expected

    @parameterized.expand(
        [
            (
                "one_key",
                "if(event = '$feature_flag_called' AND properties.$feature_flag = 'probe-flag', 1, 0) AS step_1",
                "step_1 = 1",
                "tuple('probe-flag')",
            ),
            (
                "a_key_per_step_with_other_conditions",
                "if(event = '$feature_flag_called' AND properties.$feature_flag = 'a' AND properties.x = '1', 1, 0) "
                "AS step_1, "
                "if(event = '$feature_flag_called' AND properties.$feature_flag = 'b' AND properties.x = '2', 1, 0) "
                "AS step_2",
                "step_1 = 1 OR step_2 = 1",
                "tuple('a', 'b')",
            ),
        ]
    )
    def test_funnel_steps_on_flag_keys_read_only_those_keys_and_skip_keyless_calls(
        self, _name: str, flag_steps: str, flag_step_filter: str, keys: str
    ):
        # The shape a funnel runner builds: one column per step, and a filter that keeps a row matching any step.
        sql = self._sql(
            "SELECT * FROM ("
            f"SELECT if(event = '$pageview', 1, 0) AS step_0, {flag_steps} "
            "FROM events WHERE timestamp >= toDateTime('2026-10-01') AND timestamp <= toDateTime('2026-10-20') "
            f"AND event IN ('$feature_flag_called', '$pageview') AND (step_0 = 1 OR {flag_step_filter}))"
        )

        events, flag_evaluations = self._branches(sql)
        for branch in (events, flag_evaluations):
            assert "2026-10-01" in branch and "2026-10-20" in branch
        assert f"in(flag_evaluations.flag_key, {keys})" in flag_evaluations
        assert "in(events.event, tuple('$feature_flag_called', '$pageview'))" in events

    @parameterized.expand(
        [
            ("no_flag_key_filter", "", None),
            # A Boolean type converts the key before the comparison, so 'TRUE' also matches the JSON value true.
            ("boolean_flag_key", " AND properties.$feature_flag = 'TRUE'", "Boolean"),
        ]
    )
    def test_query_without_a_string_flag_key_reads_keyless_calls_from_events(
        self, _name: str, flag_key_filter: str, flag_key_type: str | None
    ):
        if flag_key_type is not None:
            PropertyDefinition.objects.create(
                team=self.team, name="$feature_flag", property_type=flag_key_type, type=PropertyDefinition.Type.EVENT
            )

        events, keyless, flag_evaluations = self._branches(
            self._sql(f"SELECT count() FROM events WHERE {MIXED} AND distinct_id = 'probe'{flag_key_filter}")
        )

        for branch in (events, keyless):
            assert "equals(events.distinct_id, 'probe')" in branch
        assert "equals(flag_evaluations.distinct_id, 'probe')" in flag_evaluations
        assert "flag_key" not in flag_evaluations

    @parameterized.expand(
        [
            ("array_join", "arrayJoin(['a', 'b']) = 'a'", "arrayJoin"),
            ("random", "rand() % 10 = 0", "rand"),
            ("row_number", "rowNumberInBlock() < 5", "rowNumberInBlock"),
            ("random_in_upper_case", "RAND() % 10 = 0", "rand"),
            ("now_in_block", "timestamp < nowInBlock('UTC')", "nowInBlock"),
        ]
    )
    def test_filter_that_depends_on_each_read_stays_out_of_the_branches(self, _name: str, condition: str, name: str):
        sql = self._sql(f"SELECT count() FROM events WHERE {MIXED} AND {condition}")

        assert all(name not in branch for branch in self._branches(sql))
        assert name in sql

    def test_sample_one_adds_no_warning(self):
        _set_mode(self.organization, READ)
        with _enabled_flags(union=True):
            _, context = HogQLQueryExecutor(
                query=f"SELECT count() FROM events SAMPLE 1 WHERE {MIXED}", team=self.team
            ).generate_clickhouse_sql()

        assert context.warnings == []

    def test_sessions_join_keeps_its_time_bound(self):
        sql = self._sql(
            f"SELECT session.$session_duration FROM events WHERE {MIXED} "
            "AND timestamp >= toDateTime('2026-10-01') AND timestamp < toDateTime('2026-10-08')"
        )

        sessions = sql[sql.index("FROM raw_sessions") : sql.index("AS events__session")]
        assert "toDateTime('2026-10-01', 'UTC')" in sessions and "toDateTime('2026-10-08', 'UTC')" in sessions

    def test_sessions_join_keeps_a_literal_session_id_filter(self):
        sql = self._sql(
            f"SELECT session.$session_duration FROM events WHERE {MIXED} AND $session_id IN ('{SESSION_ID}')"
        )

        sessions = sql[sql.index("FROM raw_sessions") : sql.index("AS events__session")]
        assert (
            f"in(raw_sessions.session_id_v7, tuple(toUInt128(accurateCastOrNull('{SESSION_ID}', 'UUID'))))" in sessions
        )

    def test_persons_join_runs_one_override_join(self):
        sql = self._sql(
            f"SELECT person_id, person.properties.email FROM events WHERE {MIXED}",
            persons_on_events=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
        )

        assert sql.count("FROM person_distinct_id_overrides") == 2  # one inner, one outer for `person_id`

    def test_typed_property_converts_once_at_its_read_and_stays_raw_in_the_branches(self):
        for kind in (PropertyDefinition.Type.EVENT, PropertyDefinition.Type.PERSON):
            PropertyDefinition.objects.create(team=self.team, name="amount", property_type="Numeric", type=kind)
        sql = self._sql(
            f"SELECT toFloatOrZero(properties.amount), properties.amount FROM events "
            f"WHERE {MIXED} AND properties.amount > 9 AND person.properties.amount > 9",
            persons_on_events=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
        )

        assert "accurateCastOrNull(accurateCastOrNull" not in sql
        assert "toFloat64OrZero(events.properties___amount)" in sql
        for branch in self._branches(sql):
            projection, _, where = branch.partition(" FROM ")
            assert "accurateCastOrNull" not in projection
            assert where.count("accurateCastOrNull") == 1
        # The persons join comes after the union, so it converts its property as it does on events.
        assert "accurateCastOrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, 'amount')" in sql


class TestFlagCallsUnionRows(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        now = datetime.now(UTC)
        self.recent = _create_person(distinct_ids=["recent"], team_id=self.team.pk, properties={"email": "r@x.com"})
        self.old = _create_person(distinct_ids=["old"], team_id=self.team.pk, properties={"email": "o@x.com"})
        for distinct_id, person, days_ago in (("recent", self.recent, 3), ("old", self.old, 100)):
            _create_event(
                event="$pageview",
                distinct_id=distinct_id,
                person_id=person.uuid,
                person_properties={"email": person.properties["email"]},
                team=self.team,
                timestamp=now - timedelta(days=days_ago),
            )
        # Ingestion writes a keyed flag call to both tables on mode 1. Only flag_evaluations has the stale person,
        # which an override corrects.
        flag_call_uuid = uuid.uuid4()
        _create_event(
            event_uuid=flag_call_uuid,
            event="$feature_flag_called",
            distinct_id="recent",
            person_id=self.recent.uuid,
            person_properties={"email": "r@x.com"},
            team=self.team,
            timestamp=now - timedelta(days=2),
            properties={"$feature_flag": "probe-flag", "source": "events"},
        )
        _create_flag_evaluations(
            self.team.pk,
            "probe-flag",
            timestamp=now - timedelta(days=2),
            distinct_id="recent",
            person_id=uuid.uuid4(),
            person_properties={"email": "r@x.com"},
            properties={"source": "flag_evaluations"},
        )
        sync_execute(
            "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version) VALUES",
            [(self.team.pk, "recent", str(self.recent.uuid), 1)],
        )
        _create_event(
            event="$feature_flag_called",
            distinct_id="old",
            person_id=self.old.uuid,
            team=self.team,
            timestamp=now - timedelta(days=99),
            properties={"$feature_flag": "probe-flag", "source": "events"},
        )
        for distinct_id, flag_key in (("missing", None), ("empty", ""), ("number", 100)):
            _create_event(
                event="$feature_flag_called",
                distinct_id=distinct_id,
                team=self.team,
                timestamp=now - timedelta(days=1),
                properties={"source": "events", **({} if flag_key is None else {"$feature_flag": flag_key})},
            )
        flush_persons_and_events()

    def _run(
        self,
        query: str | ast.SelectQuery,
        mode: FlagEvaluationsMode,
        persons_on_events: PersonsOnEventsMode | None = None,
    ):
        _set_mode(self.organization, mode)
        with _enabled_flags(union=True):
            return execute_hogql_query(
                query,
                team=self.team,
                modifiers=HogQLQueryModifiers(
                    personsOnEventsMode=persons_on_events, useNewEventsSchema=_events_schema_for(mode, None)
                ),
            )

    @parameterized.expand(
        [
            (f"{mode.name.lower()}_{poe.name.lower()}", mode, poe)
            for mode in (FlagEvaluationsMode.READ_FLAG_EVALUATIONS, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)
            for poe in (
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            )
        ]
    )
    def test_each_flag_call_comes_from_one_table(self, _name: str, mode: FlagEvaluationsMode, poe: PersonsOnEventsMode):
        response = self._run(
            f"""
            SELECT distinct_id, event, properties.source, person_id, person.properties.email
            FROM events
            WHERE {MIXED} AND timestamp >= now() - INTERVAL 120 DAY
            ORDER BY timestamp, distinct_id
            """,
            mode,
            poe,
        )

        recent_id, old_id = str(self.recent.uuid), str(self.old.uuid)
        history = [
            ("old", "$pageview", None, old_id, "o@x.com"),
            ("old", "$feature_flag_called", "events", old_id, "o@x.com"),
        ]
        recent = [
            ("recent", "$pageview", None, recent_id, "r@x.com"),
            ("recent", "$feature_flag_called", "flag_evaluations", recent_id, "r@x.com"),
        ]
        keyless = [(distinct_id, "$feature_flag_called", "events") for distinct_id in ("empty", "missing", "number")]
        rows = [
            tuple(str(value) if isinstance(value, uuid.UUID) else value for value in row) for row in response.results
        ]
        if mode == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY:
            assert rows == [history[0], *recent]
        else:
            assert rows[:4] == [*history, *recent]
            assert [row[:3] for row in rows[4:]] == keyless

    @parameterized.expand(
        [
            (f"{kind.name.lower()}_{mode.name.lower()}", kind, mode)
            for kind in (PropertyDefinition.Type.EVENT, PropertyDefinition.Type.PERSON)
            for mode in (READ, ONLY)
        ]
    )
    def test_string_parser_reads_the_raw_value_of_a_typed_property(
        self, _name: str, kind: PropertyDefinition.Type, mode: FlagEvaluationsMode
    ):
        PropertyDefinition.objects.create(team=self.team, name="amount", property_type="Numeric", type=kind)
        now = datetime.now(UTC)
        person = _create_person(distinct_ids=["typed"], team_id=self.team.pk)
        for amount in ("9", "20"):
            _create_event(
                event="$pageview",
                distinct_id="typed",
                person_id=person.uuid,
                person_properties={"amount": amount},
                team=self.team,
                timestamp=now - timedelta(days=1),
                properties={"amount": amount},
            )
        _create_event(
            event="$feature_flag_called",
            distinct_id="typed",
            person_id=person.uuid,
            person_properties={"amount": "12.5"},
            team=self.team,
            timestamp=now - timedelta(days=1),
            properties={"$feature_flag": "typed-flag", "source": "events", "amount": "12.5"},
        )
        _create_flag_evaluations(
            self.team.pk,
            "typed-flag",
            timestamp=now - timedelta(days=1),
            distinct_id="typed",
            person_id=person.uuid,
            person_properties={"amount": "12.5"},
            properties={"source": "flag_evaluations", "amount": "12.5"},
        )
        flush_persons_and_events()
        amount = "properties.amount" if kind == PropertyDefinition.Type.EVENT else "person.properties.amount"

        # Compared as text, "20" and "12.5" sort before "9", so a raw read in any branch or above it drops them.
        response = self._run(
            f"SELECT event, properties.source, toFloatOrZero({amount}) FROM events "
            f"WHERE {MIXED} AND distinct_id = 'typed' AND {amount} > 9 ORDER BY event",
            mode,
            PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
        )

        assert response.results == [("$feature_flag_called", "flag_evaluations", 12.5), ("$pageview", None, 20.0)]

    def test_prewhere_reads_both_tables(self):
        response = self._run(
            f"SELECT count() FROM events PREWHERE {MIXED} WHERE timestamp >= now() - INTERVAL 120 DAY",
            FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
        )

        assert response.results == [(7,)]

    @parameterized.expand([("json",), ("materialized",)])
    def test_keyless_flag_calls_come_from_events(self, read: str):
        # A materialized $feature_flag column reads an empty string as missing.
        if read == "materialized":
            self.addCleanup(cleanup_materialized_columns)
            materialize("events", "$feature_flag")
        response = self._run(
            f"SELECT distinct_id FROM events WHERE {MIXED} AND event = '$feature_flag_called' "
            "AND timestamp >= now() - INTERVAL 5 DAY ORDER BY distinct_id",
            FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
        )

        assert response.results == [("empty",), ("missing",), ("number",), ("recent",)]

    @parameterized.expand(
        [
            (
                "pin_of_one_flag_key",
                "SELECT distinct_id, event, properties.source FROM events WHERE event = '$pageview' "
                "OR (event = '$feature_flag_called' AND properties.$feature_flag = 'probe-flag') ORDER BY timestamp",
                [
                    ("old", "$pageview", None),
                    ("old", "$feature_flag_called", "events"),
                    ("recent", "$pageview", None),
                    ("recent", "$feature_flag_called", "flag_evaluations"),
                ],
            ),
            # The OR reads a person property, so no branch can copy it.
            (
                "or_with_a_person_property",
                f"SELECT distinct_id, event, properties.source FROM events WHERE {MIXED} "
                "AND (event = '$pageview' OR person.properties.email = 'r@x.com') "
                "AND timestamp >= now() - INTERVAL 5 DAY ORDER BY timestamp",
                [("recent", "$pageview", None), ("recent", "$feature_flag_called", "flag_evaluations")],
            ),
            (
                "global_join",
                _global_join(
                    "SELECT e.distinct_id, e.event, e.properties.source FROM events AS e "
                    "INNER JOIN (SELECT 'recent' AS distinct_id) AS r ON e.distinct_id = r.distinct_id "
                    f"WHERE {E_MIXED} AND e.timestamp >= now() - INTERVAL 5 DAY ORDER BY e.timestamp"
                ),
                [("recent", "$pageview", None), ("recent", "$feature_flag_called", "flag_evaluations")],
            ),
        ]
    )
    def test_branch_filters_keep_every_row_the_query_keeps(
        self, _name: str, query: str | ast.SelectQuery, expected: list[tuple]
    ):
        response = self._run(
            query,
            FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
            PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
        )

        assert response.results == expected

    def test_exception_values_read_as_an_array(self):
        query = f"SELECT count() FROM events WHERE {MIXED} AND has(properties.$exception_values, 'probe')"

        assert self._run(query, FlagEvaluationsMode.READ_FLAG_EVALUATIONS).results == [(0,)]

    def test_restricted_property_is_hidden_in_every_branch(self):
        _restrict(self.organization, self.team, "source")
        query = f"SELECT properties.source FROM events WHERE {MIXED}"

        assert {row[0] for row in self._run(query, FlagEvaluationsMode.READ_FLAG_EVALUATIONS).results} == {None}
        assert (
            self._run(f"{query} AND properties.source = 'events'", FlagEvaluationsMode.READ_FLAG_EVALUATIONS).results
            == []
        )

    @parameterized.expand(
        [
            (f"{poe.name.lower()}_{'events_json' if new_schema else 'events'}", poe, new_schema)
            for poe in (
                PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            )
            for new_schema in (False, True)
        ]
    )
    def test_every_events_field_reads_the_same_type_or_keeps_events(
        self, _name: str, poe: PersonsOnEventsMode, new_schema: bool
    ):
        # Mode 1 keeps reading events on the native JSON table, so only mode 2 reads the union there.
        _set_mode(self.organization, ONLY if new_schema else READ)
        create_group_type_mapping(team=self.team, group_type="organization", group_type_index=0)
        # A typed property reads as a number, which the union keeps only when it converts the read above the branches.
        for property_type in (PropertyDefinition.Type.EVENT, PropertyDefinition.Type.PERSON):
            PropertyDefinition.objects.create(team=self.team, name="probe", property_type="Numeric", type=property_type)
        modifiers = HogQLQueryModifiers(personsOnEventsMode=poe, useNewEventsSchema=new_schema)
        with _enabled_flags(union=True):
            union_database = Database.create_for(team=self.team, modifiers=modifiers)
        with _enabled_flags(union=False):
            events_database = Database.create_for(team=self.team, modifiers=modifiers)

        def sql(query: str, database: Database) -> str:
            context = HogQLContext(
                team_id=self.team.pk, team=self.team, database=database, modifiers=modifiers, enable_select_queries=True
            )
            return prepare_and_print_ast(parse_select(query), context, "clickhouse")[0]

        accepted = []
        for chain in _readable_chains(union_database):
            name = ".".join(f"`{part}`" for part in chain)
            try:
                sql(f"SELECT {name} FROM events", events_database)
            except QueryError:
                continue
            # A field the union cannot read keeps the query on events on mode 1 and fails it on mode 2.
            try:
                union_sql = sql(f"SELECT {name} FROM events WHERE {MIXED}", union_database)
            except QueryError:
                continue
            if "UNION ALL" in union_sql:
                accepted.append(name)

        assert {
            "`timestamp`",
            "`properties`.`probe`",
            "`person_id`",
            "`person`.`properties`.`probe`",
            "`$session_id`",
            "`elements_chain_texts`",
            "`$group_0`",
            # The sessions join reads `$session_id_uuid`, which is not its key.
            "`session`.`id`",
        } <= set(accepted)
        types: dict[bool, dict[str, str]] = {False: {}, True: {}}
        # One query per few fields keeps each union within the memory of a local ClickHouse.
        for offset in range(0, len(accepted), 8):
            names = accepted[offset : offset + 8]
            types_query = f"SELECT {', '.join(f'toTypeName(any({name}))' for name in names)} FROM events WHERE {MIXED}"
            for union in (False, True):
                with _enabled_flags(union=union):
                    response = execute_hogql_query(types_query, team=self.team, modifiers=modifiers)
                types[union].update(zip(names, response.results[0]))

        # flag_evaluations has no elements, and its empty Array(String) widens the union of the events Enum8 array.
        # Comparisons with string literals behave the same on both types.
        widened = {"`elements_chain_elements`": "Array(String)"}
        assert types[True] == {**types[False], **widened}


def _events_schema_for(mode: FlagEvaluationsMode, new_events_schema: bool | None) -> bool | None:
    # Mode 1 keeps reading events on the native JSON table, so a mode 1 case reads the legacy table unless it asks.
    if new_events_schema is None and mode == READ:
        return False
    return new_events_schema


def _readable_chains(database: Database) -> list[list[str | int]]:
    """A chain to select for each events field, and for one field behind each of its joins."""
    events = database.get_table("events")
    chains: list[list[str | int]] = []
    for name, field in events.fields.items():
        if isinstance(field, (LazyJoin, FieldTraverser)):
            chains.extend([[name, "id"], [name, "properties", "probe"], [name, "person_id"]])
            continue
        inner_fields = field.fields.items() if isinstance(field, VirtualTable) else [(None, field)]
        for inner_name, inner in inner_fields:
            chain: list[str | int] = [name] if inner_name is None else [name, inner_name]
            if isinstance(inner, StringJSONDatabaseField):
                chains.append([*chain, "probe"])
            elif isinstance(inner, DatabaseField):
                chains.append(chain)
    return chains
