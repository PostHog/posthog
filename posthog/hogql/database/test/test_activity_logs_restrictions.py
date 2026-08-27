from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import create_default_modifiers_for_team

from posthog.models.activity_logging.retention import get_activity_log_lookback_restriction
from posthog.models.activity_logging.visibility_rules import activity_visibility_restrictions

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

    def _print(self, query: str = "SELECT id FROM system.activity_logs") -> tuple[str, dict]:
        context = self._context()
        sql = prepare_and_print_ast(parse_select(query), context, dialect="clickhouse")[0]
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

    def test_rules_print_as_one_negated_match_each(self):
        self._set_audit_logs_feature(limit=30, unit="days")

        sql, _ = self._print()

        self.assertEqual(
            sql.count("not(and(equals(system__activity_logs.scope,"),
            len(activity_visibility_restrictions),
        )

    def test_printing_a_query_without_activity_logs_costs_no_extra_query(self):
        # The organization load is lazy: an ordinary HogQL query must not pay a Postgres round trip.
        context = self._context()
        select = parse_select("SELECT id FROM system.insights")

        with self.assertNumQueries(0):
            prepare_and_print_ast(select, context, dialect="clickhouse")
