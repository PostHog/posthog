from datetime import UTC, datetime

from posthog.test.base import APIBaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.models.group_type_mapping import invalidate_group_types_cache
from posthog.test.persons import create_group_type_mapping


class TestGroupsJoinPrefilter(APIBaseTest):
    """
    Each `LEFT JOIN groups` subquery generated for `group_N.<field>` access should also be
    constrained by `group_key IN (SELECT $group_N FROM events WHERE <outer prefilter>)` when
    the outer query has a `timestamp`-bounded WHERE. Without that constraint the join hash
    table contains every group of that type for the team, decompressing the wide
    `group_properties` blob row-by-row — enough to OOM the query on a high-volume team even
    when only a handful of events are actually selected.

    The optimization is gated on `timestamp` appearing in the outer WHERE, so unbounded
    queries (no WHERE, or WHERE without a date range) still go through the original path.
    """

    def setUp(self):
        super().setUp()
        create_group_type_mapping(
            team=self.team,
            project=self.team.project,
            group_type="company",
            group_type_index=0,
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        invalidate_group_types_cache(self.team.project_id)
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team=self.team, database=self.database, enable_select_queries=True)

    def _print(self, query: str) -> str:
        sql, _ = prepare_and_print_ast(parse_select(query), context=self.context, dialect="clickhouse")
        return sql

    def test_pushes_group_key_filter_when_outer_where_has_timestamp(self):
        sql = self._print("SELECT group_0.properties FROM events WHERE timestamp > toDateTime('2026-01-01') LIMIT 10")
        # Groups subquery now constrains group_key to the keys present in the matched events.
        # The `$group_0` field reference can be wrapped by the resolver (timestamp clamping
        # against the GroupTypeMapping created_at, etc.), so we only assert the column ref
        # appears in the printed SQL — not the exact SELECT prefix.
        self.assertIn("in(key,", sql)
        self.assertIn("events.`$group_0`", sql)
        self.assertIn("FROM events", sql)

    def test_pushes_group_key_filter_with_uuid_and_timestamp_where(self):
        # Mirrors the prod test-event-fetch shape: uuid set plus a tight timestamp window.
        sql = self._print(
            "SELECT group_0.properties FROM events "
            "WHERE uuid IN ('019ef62f-21be-7867-9939-e0723c27efc2') "
            "AND timestamp > toDateTime('2026-06-23 02:48:28') "
            "AND timestamp < toDateTime('2026-06-23 13:32:26')"
        )
        self.assertIn("in(key,", sql)
        self.assertIn("events.`$group_0`", sql)

    def test_skips_filter_when_outer_where_lacks_timestamp(self):
        # No timestamp reference → the optimization would push a key subquery that scans every
        # event for the team, which is strictly worse than no filter. Guard skips it.
        sql = self._print("SELECT group_0.properties FROM events WHERE event = '$pageview'")
        self.assertNotIn("in(key,", sql)

    def test_skips_filter_when_outer_has_no_where(self):
        sql = self._print("SELECT group_0.properties FROM events")
        self.assertNotIn("in(key,", sql)

    def test_skips_filter_when_outer_where_references_lazy_join(self):
        # Cloning a WHERE that references a lazy-join column (e.g. `group_0.properties.X`)
        # into the inner `SELECT $group_N FROM events ...` subquery would re-trigger the
        # same lazy join inside that inner subquery during resolution — producing unbounded
        # recursion or a `ResolutionError`. The guard skips the optimization in that case;
        # the outer group join still resolves and prints normally, just without the key
        # prefilter pushed into its WHERE.
        sql = self._print(
            "SELECT group_0.properties FROM events "
            "WHERE group_0.properties.industry = 'tech' "
            "AND timestamp > toDateTime('2026-01-01')"
        )
        self.assertIn("events__group_0", sql)
        self.assertNotIn("in(key,", sql)

    def test_skips_filter_when_outer_where_references_person_lazy_join(self):
        # Same recursive-resolution risk for `person.*` references on the events table.
        sql = self._print(
            "SELECT group_0.properties FROM events "
            "WHERE person.properties.plan = 'pro' "
            "AND timestamp > toDateTime('2026-01-01')"
        )
        self.assertIn("events__group_0", sql)
        self.assertNotIn("in(key,", sql)

    def test_skips_filter_when_outer_from_events_is_aliased(self):
        # Funnel queries (and others) build `FROM events AS e ... WHERE e.timestamp > X`.
        # Cloning that WHERE into the inner `SELECT $group_N FROM events` subquery would
        # carry references to `e.X` that have no scope in the inner subquery, raising
        # `Unable to resolve field: e`. Guard skips the optimization for aliased FROMs.
        sql = self._print("SELECT group_0.properties FROM events AS e WHERE e.timestamp > toDateTime('2026-01-01')")
        # The lazy join is named after the FROM alias, so `e__group_0` rather than `events__group_0`.
        self.assertIn("e__group_0", sql)
        self.assertNotIn("in(key,", sql)
