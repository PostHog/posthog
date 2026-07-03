"""Tests the ``within_non_hogql_query`` lightweight-DELETE-mutation path.

Data deletion compiles a HogQL property predicate into a ClickHouse fragment via ``compile_hogql_predicate`` (which sets
``within_non_hogql_query=True``), and the deletion DAG splices that fragment into a lightweight
``DELETE FROM sharded_events WHERE …`` mutation. The catch: a ClickHouse lightweight-delete expression analyzer rejects
table-qualified column references, so when the predicate hits a materialized column the fragment must read it
**unqualified** — ``mat_$browser``, never ``sharded_events.mat_$browser`` — even though the column exists on every
replica. The DAG tests (``posthog/dags/tests/test_data_deletion_requests.py``) cover the delete flow only over an
unmaterialized property, so the materialized-column case is tested here.

This file checks two things:

1. ``compile_hogql_predicate`` over ``properties.$browser = 'Chrome'`` with ``$browser`` materialized produces an
   unqualified fragment (no ``events.`` / ``sharded_events.`` prefix on the mat column) using only mutation-safe scalar
   functions.
2. A real lightweight DELETE built from that fragment (mirroring the production ``LightweightDeleteMutationRunner``
   statement and settings) removes the matching rows and leaves the non-matching and other-team rows in place.
"""

import re
from typing import cast

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    cleanup_materialized_columns,
    flush_persons_and_events,
    materialized,
)

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.hogql import translate_hogql

from posthog.clickhouse.client.execute import sync_execute
from posthog.models import Organization, Team
from posthog.models.data_deletion_request import compile_hogql_predicate
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.property import TableColumn
from posthog.settings.data_stores import CLICKHOUSE_DATABASE


class _PredicateObj:
    """Minimal stand-in for the deletion-request shape ``compile_hogql_predicate`` reads (``team_id`` + predicate)."""

    def __init__(self, team_id: int, hogql_predicate: str) -> None:
        self.team_id = team_id
        self.hogql_predicate = hogql_predicate


# Functions a ClickHouse lightweight-delete mutation expression analyzer accepts: plain scalar functions. The compiled
# fragment for a property predicate must use only these (no aggregates, no table-qualified columns, no window/array
# higher-order forms). This is the allow-list the form constraint cares about.
_MUTATION_SAFE_FUNCTIONS = frozenset(
    {
        "equals",
        "notequals",
        "and",
        "or",
        "not",
        "ifnull",
        "isnull",
        "isnotnull",
        "nullif",
        "in",
        "notin",
        "has",
        "jsonextractraw",
        "jsonextractstring",
        "jsonhas",
        "replaceregexpall",
        "tostring",
        "like",
        "ilike",
        "lower",
        "greater",
        "less",
        "greaterorequals",
        "lessorequals",
    }
)


class TestWithinNonHogqlDelete(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _materialized_column_name(self, table: str, prop: str, table_column: str = "properties") -> str:
        from ee.clickhouse.materialized_columns.columns import get_materialized_columns  # noqa: PLC0415

        column = get_materialized_columns(table).get((prop, cast(TableColumn, table_column)))
        assert column is not None, f"expected materialized column for {table}.{prop} ({table_column})"
        return column.name

    def _assert_unqualified_and_mutation_safe(self, sql: str, expected_column_sql: str) -> None:
        sql_lower = sql.lower()
        expected_column_sql_lower = expected_column_sql.lower()

        # Unqualified — the lightweight-delete mutation analyzer rejects table-qualified column references.
        assert f"events.{expected_column_sql_lower}" not in sql_lower, (
            f"predicate column must be unqualified, got: {sql}"
        )
        assert "events." not in sql_lower, f"fragment must carry no table prefix at all, got: {sql}"
        assert "sharded_events." not in sql_lower, f"fragment must carry no table prefix at all, got: {sql}"
        # The unqualified physical property read must be present — confirms the mutation uses the active schema shape.
        assert expected_column_sql_lower in sql_lower, f"expected the property column {expected_column_sql} in: {sql}"

        # Mutation-safe: every function name used is on the scalar allow-list (no aggregates / unsafe forms).
        called = {name.lower() for name in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", sql)}
        unexpected = called - _MUTATION_SAFE_FUNCTIONS
        assert not unexpected, f"fragment uses non-mutation-safe functions {unexpected} in: {sql}"

    def _expected_browser_property_sql(self) -> str:
        return self._materialized_column_name("events", "$browser")

    def test_compiled_predicate_is_unqualified_and_mutation_safe_with_materialized_column(self) -> None:
        self.addCleanup(cleanup_materialized_columns)
        with materialized("events", "$browser", is_nullable=False):
            sql, params = compile_hogql_predicate(_PredicateObj(self.team.pk, "properties.$browser = 'Chrome'"))

            self._assert_unqualified_and_mutation_safe(sql, self._expected_browser_property_sql())
            # The compared value is parameterized (not inlined), and resolves to the literal we passed.
            assert params == {"hogql_val_0": "Chrome"}, params

    def test_within_non_hogql_predicate_stays_unqualified_with_materialized_column(self) -> None:
        # within_non_hogql_query queries run through lowering + the physical pass like any other: the synthetic
        # materialized-column field is marked `unqualified`, so the printer drops the table prefix and the
        # lightweight-delete mutation analyzer accepts the bare column.
        self.addCleanup(cleanup_materialized_columns)
        with materialized("events", "$browser", is_nullable=False):
            context = HogQLContext(
                team_id=self.team.pk,
                within_non_hogql_query=True,
                enable_select_queries=True,
            )
            sql = translate_hogql(
                "properties.$browser = 'Chrome'",
                context,
                dialect="clickhouse",
                events_table_use_new_schema=False,
            )
            self._assert_unqualified_and_mutation_safe(sql, self._expected_browser_property_sql())

    def test_compiled_predicate_is_unqualified_and_mutation_safe_without_materialized_column(self) -> None:
        # Without materialization the fragment is the JSON-blob form; it must STILL be unqualified and mutation-safe
        # (the deletion path always runs with within_non_hogql_query=True). This is the other production shape.
        sql, _params = compile_hogql_predicate(_PredicateObj(self.team.pk, "properties.$browser = 'Chrome'"))

        sql_lower = sql.lower()
        assert "events." not in sql_lower, f"blob fragment must be unqualified, got: {sql}"
        assert "sharded_events." not in sql_lower, f"blob fragment must be unqualified, got: {sql}"
        assert "jsonextractraw" in sql_lower, f"expected the JSON-blob extract form, got: {sql}"
        called = {name.lower() for name in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", sql)}
        unexpected = called - _MUTATION_SAFE_FUNCTIONS
        assert not unexpected, f"blob fragment uses non-mutation-safe functions {unexpected} in: {sql}"

    def _count_browser_rows(self, team_id: int, browser: str) -> int:
        table = "events"
        browser_predicate = "JSONExtractString(properties, '$browser') = %(b)s"
        result = sync_execute(
            f"SELECT count() FROM {table} WHERE team_id = %(team_id)s AND {browser_predicate}",
            {"team_id": team_id, "b": browser},
        )
        return result[0][0]

    def _run_lightweight_delete(self, team_id: int, predicate_fragment: str, params: dict) -> None:
        # Mirror production ``LightweightDeleteMutationRunner.get_statement``: a lightweight ``DELETE FROM`` against the
        # local sharded table, scoped by team_id (the compiled fragment carries no team guard of its own) AND the
        # compiled predicate. Synchronous settings so the mutation completes before we assert.
        table = EVENTS_DATA_TABLE()
        delete_sql = (
            f"DELETE FROM {CLICKHOUSE_DATABASE}.{table} "  # nosemgrep: clickhouse-fstring-param-audit
            f"WHERE team_id = %(_del_team_id)s AND ({predicate_fragment})"
        )
        sync_execute(
            delete_sql,
            {**params, "_del_team_id": team_id},
            settings={"lightweight_deletes_sync": 2, "mutations_sync": 2},
        )

    @parameterized.expand([("materialized", True), ("unmaterialized", False)])
    def test_lightweight_delete_mutation_removes_matching_rows(self, _name: str, is_materialized: bool) -> None:
        self.addCleanup(cleanup_materialized_columns)

        # A second team to prove the team_id guard keeps the delete scoped (cross-team safety).
        other_org = Organization.objects.create(name="del-other-org")
        other_team = Team.objects.create(organization=other_org, name="del-other-team")

        def seed() -> None:
            for i in range(5):
                _create_event(
                    team=self.team, distinct_id=f"chrome_{i}", event="$pageview", properties={"$browser": "Chrome"}
                )
            for i in range(3):
                _create_event(
                    team=self.team, distinct_id=f"firefox_{i}", event="$pageview", properties={"$browser": "Firefox"}
                )
            # Same matching property on a different team — must NOT be deleted.
            _create_event(
                team=other_team, distinct_id="other_chrome", event="$pageview", properties={"$browser": "Chrome"}
            )
            flush_persons_and_events()

        if is_materialized:
            with materialized("events", "$browser", is_nullable=False):
                seed()
                sql, params = compile_hogql_predicate(_PredicateObj(self.team.pk, "properties.$browser = 'Chrome'"))
                # The physical property read must be unqualified or the mutation analyzer rejects it.
                self._assert_unqualified_and_mutation_safe(sql, self._expected_browser_property_sql())
                self._run_and_assert_delete(sql, params, other_team)
        else:
            seed()
            sql, params = compile_hogql_predicate(_PredicateObj(self.team.pk, "properties.$browser = 'Chrome'"))
            self._run_and_assert_delete(sql, params, other_team)

    def _run_and_assert_delete(self, predicate_fragment: str, params: dict, other_team: Team) -> None:
        # Pre-conditions.
        self.assertEqual(self._count_browser_rows(self.team.pk, "Chrome"), 5)
        self.assertEqual(self._count_browser_rows(self.team.pk, "Firefox"), 3)
        self.assertEqual(self._count_browser_rows(other_team.pk, "Chrome"), 1)

        self._run_lightweight_delete(self.team.pk, predicate_fragment, params)

        # Chrome rows for this team are gone; Firefox rows and the other team's Chrome row survive.
        self.assertEqual(self._count_browser_rows(self.team.pk, "Chrome"), 0)
        self.assertEqual(self._count_browser_rows(self.team.pk, "Firefox"), 3)
        self.assertEqual(self._count_browser_rows(other_team.pk, "Chrome"), 1)
