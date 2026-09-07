from datetime import timedelta
from typing import Literal

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

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
from posthog.hogql.database.schema.activity_log_visibility import activity_log_visibility_policy_version
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team

from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.activity_logging.activity_log import activity_visibility_restrictions
from posthog.models.activity_logging.retention import get_activity_log_lookback_restriction
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl

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

        # toString keeps the set String-typed. Canvas ids are UUIDs, item_id is a String holding
        # mostly numeric ids, and ClickHouse coerces item_id to the set's type for every row.
        self.assertIn("NOT(and(equals(scope, 'Canvas'), notIn(item_id, (SELECT toString(id) FROM canvases", hogql)
        # The canvases subquery keeps that table's own guards, so its access control carries over.
        self.assertIn("_task_public_channels", hogql)

    def test_canvas_rows_are_dropped_when_the_canvases_table_is_denied(self):
        # Denying the canvas resource removes system.canvases from the schema, so a rule referencing it
        # would raise TableAccessDeniedError and take the whole audit trail down with it. Such a caller
        # may read no canvas at all, so the rows go instead.
        self.organization.available_product_features = [
            {"key": "audit_logs", "name": "Audit logs", "limit": 30, "unit": "days"},
            {"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"},
        ]
        self.organization.save()
        # Object and resource access control only applies to non-admins.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(team=self.team, resource="canvas", access_level="none")

        hogql, _ = self._print(dialect="hogql")

        self.assertIn("NOT(equals(scope, 'Canvas'))", hogql)
        self.assertNotIn("canvases", hogql)

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
        runner = get_query_runner(
            HogQLQuery(query="SELECT id FROM system.activity_logs"), team=self.team, user=self.user
        )
        return runner.get_cache_payload()

    def test_cache_key_varies_with_the_retention_window(self):
        # A cache hit returns before the printer applies the floor, so without this a result cached
        # on a longer plan keeps serving rows the organization is no longer entitled to read.
        with freeze_time("2026-08-14T10:30:00Z"):
            wide = self._payload(limit=365, unit="days")
            narrow = self._payload(limit=30, unit="days")

        self.assertNotEqual(wide["activity_log_retention_floor_hour"], narrow["activity_log_retention_floor_hour"])

    def test_cache_key_omits_the_floor_without_the_entitlement(self):
        self.organization.available_product_features = []
        self.organization.save()
        runner = get_query_runner(
            HogQLQuery(query="SELECT id FROM system.activity_logs"), team=self.team, user=self.user
        )

        self.assertNotIn("activity_log_retention_floor_hour", runner.get_cache_payload())

    @parameterized.expand(
        [
            ("reads the table", "SELECT id FROM system.activity_logs", True),
            ("reads another table", "SELECT id FROM system.insights", False),
        ]
    )
    def test_cache_key_carries_the_visibility_policy_version(self, _name: str, query: str, expected: bool):
        # The visibility rules are printed guards, so nothing else in the key tracks them: without this, a
        # result stored under the previous rules keeps serving the rows the current ones hide. Changing the
        # rules retires those results, so the fingerprint has to reach every query reading the table.
        runner = get_query_runner(HogQLQuery(query=query), team=self.team, user=self.user)

        payload = runner.get_cache_payload()

        self.assertEqual("activity_log_visibility_policy" in payload, expected)

    def test_the_visibility_policy_version_tracks_the_rule_list(self):
        # The fingerprint exists so that editing the shared rule list is enough to retire the results the
        # previous rules produced. One that ignored the list would keep serving rows the new rules hide.
        self.addCleanup(activity_log_visibility_policy_version.cache_clear)
        before = activity_log_visibility_policy_version()

        activity_log_visibility_policy_version.cache_clear()
        with patch(
            "posthog.models.activity_logging.activity_log.activity_visibility_restrictions",
            [*activity_visibility_restrictions, {"scope": "Insight", "activities": ["deleted"]}],
        ):
            after = activity_log_visibility_policy_version()

        self.assertNotEqual(before, after)

    def test_cache_key_follows_the_floor_as_it_moves(self):
        # A cache-only request returns a stored result however stale it is, so a result stored inside the
        # window would keep serving its rows after they fall outside it. Keying on the window rather than
        # on the floor would miss that, because the window does not change as the clock moves.
        self.organization.available_product_features = [
            {"key": "audit_logs", "name": "Audit logs", "limit": 30, "unit": "days"}
        ]
        self.organization.save()

        with freeze_time("2026-08-14T10:30:00Z"):
            earlier = get_query_runner(
                HogQLQuery(query="SELECT id FROM system.activity_logs"), team=self.team, user=self.user
            ).get_cache_key()
        with freeze_time("2026-08-14T11:30:00Z"):
            later = get_query_runner(
                HogQLQuery(query="SELECT id FROM system.activity_logs"), team=self.team, user=self.user
            ).get_cache_key()

        self.assertNotEqual(earlier, later)
