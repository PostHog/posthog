"""Execution test for the ``within_non_hogql_query`` lightweight-DELETE-mutation path (printer rearchitecture, §8.4).

This is the genuinely missing net the design doc calls out. ``compile_hogql_predicate`` (the data-deletion entry point)
compiles a HogQL property predicate into a ClickHouse fragment with ``within_non_hogql_query=True``, which the deletion
DAG splices into a lightweight ``DELETE FROM sharded_events WHERE …`` mutation. That path is high-volume in
production. The dags tests (``posthog/dags/tests/test_data_deletion_requests.py``) already run the full
``compile_hogql_predicate`` → delete flow, but only over an *unmaterialized* property — none exercise the part §8.4 is
actually about: a predicate that references a **materialized column**, which the lightweight-delete expression analyzer
requires to be **unqualified** (it rejects ``sharded_events.mat_$browser`` even when the column exists on every replica).

This file pins that. It:

1. Compiles ``properties.$browser = 'Chrome'`` via ``compile_hogql_predicate`` with ``$browser`` materialized and
   asserts the fragment is unqualified (no ``events.`` / ``sharded_events.`` prefix on the mat column) and uses only
   mutation-safe scalar functions.
2. Runs a real lightweight DELETE against the test ``sharded_events`` table using that compiled fragment (mirroring the
   production ``LightweightDeleteMutationRunner`` statement and settings), then asserts the matching rows are gone and
   the non-matching / other-team rows survive.

It characterizes correct MASTER behavior and adds no production code.
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
# higher-order forms). This is the allow-list the §8.4 form constraint cares about.
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

    def _assert_unqualified_and_mutation_safe(self, sql: str, mat_column_name: str) -> None:
        sql_lower = sql.lower()

        # §8.4: unqualified — the lightweight-delete mutation analyzer rejects table-qualified column references.
        assert f"events.{mat_column_name.lower()}" not in sql_lower, f"mat column must be unqualified, got: {sql}"
        assert "events." not in sql_lower, f"fragment must carry no table prefix at all, got: {sql}"
        assert "sharded_events." not in sql_lower, f"fragment must carry no table prefix at all, got: {sql}"
        # The bare (unqualified) materialized column must be present — confirms it was actually used.
        assert mat_column_name.lower() in sql_lower, f"expected the materialized column {mat_column_name} in: {sql}"

        # Mutation-safe: every function name used is on the scalar allow-list (no aggregates / unsafe forms).
        called = {name.lower() for name in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", sql)}
        unexpected = called - _MUTATION_SAFE_FUNCTIONS
        assert not unexpected, f"fragment uses non-mutation-safe functions {unexpected} in: {sql}"

    def test_compiled_predicate_is_unqualified_and_mutation_safe_with_materialized_column(self) -> None:
        self.addCleanup(cleanup_materialized_columns)
        with materialized("events", "$browser", is_nullable=False):
            mat_name = self._materialized_column_name("events", "$browser")
            sql, params = compile_hogql_predicate(_PredicateObj(self.team.pk, "properties.$browser = 'Chrome'"))

            self._assert_unqualified_and_mutation_safe(sql, mat_name)
            # The compared value is parameterized (not inlined), and resolves to the literal we passed.
            assert params == {"hogql_val_0": "Chrome"}, params

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
        # Read through the Distributed ``events`` proxy; in the single-shard test cluster it reflects ``sharded_events``.
        result = sync_execute(
            "SELECT count() FROM events WHERE team_id = %(team_id)s AND JSONExtractString(properties, '$browser') = %(b)s",
            {"team_id": team_id, "b": browser},
        )
        return result[0][0]

    def _run_lightweight_delete(self, team_id: int, predicate_fragment: str, params: dict) -> None:
        # Mirror production ``LightweightDeleteMutationRunner.get_statement``: a lightweight ``DELETE FROM`` against the
        # local sharded table, scoped by team_id (the compiled fragment carries no team guard of its own) AND the
        # compiled predicate. Synchronous settings so the mutation completes before we assert.
        table = EVENTS_DATA_TABLE()  # "sharded_events"
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
                # The materialized fragment must be unqualified or the mutation analyzer rejects it (§8.4).
                self._assert_unqualified_and_mutation_safe(sql, self._materialized_column_name("events", "$browser"))
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
