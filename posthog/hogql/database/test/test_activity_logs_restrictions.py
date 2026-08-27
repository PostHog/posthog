from datetime import timedelta
from typing import Literal

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import HogQLQuery

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import (
    DANGEROUS_NoTeamIdCheckTable,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    TableNode,
)
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.activity_logging.activity_log import activity_visibility_restrictions
from posthog.models.activity_logging.retention import get_activity_log_lookback_restriction

# The SQL surface must hide what the REST viewsets hide: rows past the plan's retention window, and
# rows the visibility rules restrict. Both are printed guards, so the printed SQL is the assertion.


class TestActivityLogsSqlRestrictions(BaseTest):
    def _set_audit_logs_feature(self, **feature) -> None:
        self.organization.available_product_features = [{"key": "audit_logs", "name": "Audit logs", **feature}]
        self.organization.save()

    def _context(self) -> HogQLContext:
        return HogQLContext(
            team=self.team,
            team_id=self.team.pk,
            enable_select_queries=True,
            database=Database.create_for(team=self.team, user=self.user),
            modifiers=create_default_modifiers_for_team(self.team),
        )

    def _print(
        self,
        query: str = "SELECT id FROM system.activity_logs",
        dialect: Literal["hogql", "clickhouse"] = "clickhouse",
    ) -> tuple[str, dict]:
        context = self._context()
        sql = prepare_and_print_ast(parse_select(query), context, dialect=dialect)[0]
        return sql, context.values

    def _floor(self, values: dict):
        return next(v for v in values.values() if hasattr(v, "year"))

    def test_retention_floor_is_pushed_into_the_federated_read(self):
        # Next to the team guard inside the wrap, so Postgres prunes on (team_id, -created_at)
        # instead of copying the rows out for ClickHouse to filter.
        self._set_audit_logs_feature(limit=30, unit="days")

        sql, _ = self._print()

        self.assertIn(f"WHERE team_id = {self.team.pk} AND created_at >= %(", sql)

    @parameterized.expand(
        [
            ("days", {"limit": 30, "unit": "days"}),
            ("months", {"limit": 6, "unit": "months"}),
            ("no limits, falls back", {}),
        ]
    )
    def test_retention_window_matches_the_rest_surface(self, _name: str, feature: dict):
        # One definition behind both surfaces: drift here means SQL shows rows the API hides.
        self._set_audit_logs_feature(**feature)

        _, values = self._print()

        expected = get_activity_log_lookback_restriction(self.organization)
        assert expected is not None
        self.assertAlmostEqual(self._floor(values).timestamp(), expected.timestamp(), delta=60)

    def test_no_floor_without_the_entitlement(self):
        self.organization.available_product_features = []
        self.organization.save()

        sql, values = self._print()

        self.assertIn(f"WHERE team_id = {self.team.pk})", sql)
        self.assertEqual([v for v in values.values() if hasattr(v, "year")], [])

    def test_joined_activity_logs_keep_the_federated_guard(self):
        # A joined federated table lost its team wrap whenever it declared predicates, which made
        # ClickHouse copy the whole table out of Postgres before filtering.
        self._set_audit_logs_feature(limit=30, unit="days")

        sql, _ = self._print(
            "SELECT a.id FROM system.activity_logs AS a "
            "JOIN system.insights AS i ON a.item_id = toString(i.id) LIMIT 10"
        )

        self.assertIn(f"WHERE team_id = {self.team.pk} AND created_at >= %(", sql)

    @parameterized.expand([(rule["scope"], rule["activities"]) for rule in activity_visibility_restrictions])
    def test_every_visibility_rule_reaches_the_query(self, scope: str, activities: list[str]):
        # Fails when a rule is added to the shared list but only one compiler covers it.
        self._set_audit_logs_feature(limit=30, unit="days")

        _, values = self._print()

        bound = list(values.values())
        self.assertIn(scope, bound)
        self.assertIn(activities, bound)

    def test_loop_rows_are_hidden_entirely(self):
        # The viewset allows loops per user from live RBAC. No system.loops table exists to defer
        # that to, so SQL drops the scope rather than leak another user's personal loop config.
        self._set_audit_logs_feature(limit=30, unit="days")

        hogql, _ = self._print(dialect="hogql")

        self.assertIn("NOT(equals(scope, 'Loop'))", hogql)

    def test_canvas_rows_are_limited_to_readable_canvases(self):
        # system.canvases carries its own access control, so Canvas rows defer to it instead of
        # being dropped. That table is stricter than the viewset, so this over-hides, never under.
        self._set_audit_logs_feature(limit=30, unit="days")

        hogql, _ = self._print(dialect="hogql")

        self.assertIn("NOT(and(equals(scope, 'Canvas'), notIn(item_id, (SELECT id FROM canvases", hogql)
        # The canvases subquery keeps that table's own guards, so its access control carries over.
        self.assertIn("_task_public_channels", hogql)

    def test_printing_a_query_without_activity_logs_costs_no_extra_query(self):
        # The organization load is lazy: an ordinary HogQL query must not pay a Postgres round trip.
        # Print once first, so the process-global primary-key cache is warm either way and this does
        # not depend on some earlier test in the file having warmed it.
        prepare_and_print_ast(parse_select("SELECT id FROM system.insights"), self._context(), dialect="clickhouse")

        context = self._context()
        select = parse_select("SELECT id FROM system.insights")

        with self.assertNumQueries(0):
            prepare_and_print_ast(select, context, dialect="clickhouse")

    def test_floor_survives_when_the_pushdown_wrap_does_not_apply(self):
        # The wrap in _print_table_ref is an optimization with its own preconditions. Enforcement
        # must not ride on it, so a table that skips the wrap still gets the floor in its WHERE.
        floor = timezone.now() - timedelta(days=30)

        class _UnwrappedTable(PostgresTable, DANGEROUS_NoTeamIdCheckTable):
            def retention_start(self, team, team_id):
                return floor

        context = self._context()
        assert context.database is not None
        context.database.tables.add_child(
            TableNode(
                name="unwrapped",
                table=_UnwrappedTable(
                    name="unwrapped",
                    postgres_table_name="some_unwrapped_table",
                    retention_field="created_at",
                    fields={
                        "id": IntegerDatabaseField(name="id"),
                        "created_at": DateTimeDatabaseField(name="created_at"),
                    },
                ),
            )
        )

        sql = prepare_and_print_ast(parse_select("SELECT id FROM unwrapped"), context, dialect="clickhouse")[0]

        self.assertNotIn("(SELECT * FROM postgresql(", sql)
        self.assertIn("greaterOrEquals(unwrapped.created_at, toDateTime64(", sql)
        self.assertIn(floor.strftime("%Y-%m-%d"), sql)


class TestActivityLogsCacheKey(BaseTest):
    def _payload(self, **feature) -> dict:
        self.organization.available_product_features = [{"key": "audit_logs", "name": "Audit logs", **feature}]
        self.organization.save()
        runner = get_query_runner(HogQLQuery(query="SELECT 1"), team=self.team, user=self.user)
        return runner.get_cache_payload()

    def test_cache_key_varies_with_the_retention_window(self):
        # A cache hit returns before the printer applies the floor, so without this a result cached
        # on a longer plan keeps serving rows the organization is no longer entitled to read.
        wide = self._payload(limit=365, unit="days")
        narrow = self._payload(limit=30, unit="days")

        self.assertEqual(wide["activity_log_retention_window_days"], 365)
        self.assertEqual(narrow["activity_log_retention_window_days"], 30)
        self.assertNotEqual(wide, narrow)

    def test_cache_key_omits_the_window_without_the_entitlement(self):
        self.organization.available_product_features = []
        self.organization.save()
        runner = get_query_runner(HogQLQuery(query="SELECT 1"), team=self.team, user=self.user)

        self.assertNotIn("activity_log_retention_window_days", runner.get_cache_payload())
