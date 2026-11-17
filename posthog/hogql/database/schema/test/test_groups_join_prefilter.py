from datetime import UTC, datetime

from posthog.test.base import APIBaseTest

from django.conf import settings

from parameterized import parameterized

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

    def _group_0_column(self) -> str:
        # The new table reads $group_0 as a declared JSON path, the old one as a column.
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            return "events.properties.`$group_0`"
        return "events.`$group_0`"

    def setUp(self):
        super().setUp()
        for group_type_index, group_type in enumerate(["company", "workspace"]):
            create_group_type_mapping(
                team=self.team,
                project=self.team.project,
                group_type=group_type,
                group_type_index=group_type_index,
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
        self.assertIn("globalIn(key, (SELECT DISTINCT", sql)
        self.assertIn(self._group_0_column(), sql)
        self.assertIn("FROM events", sql)

    def test_pushes_group_key_filter_with_uuid_and_timestamp_where(self):
        # Mirrors the prod test-event-fetch shape: uuid set plus a tight timestamp window.
        sql = self._print(
            "SELECT group_0.properties FROM events "
            "WHERE uuid IN ('019ef62f-21be-7867-9939-e0723c27efc2') "
            "AND timestamp > toDateTime('2026-06-23 02:48:28') "
            "AND timestamp < toDateTime('2026-06-23 13:32:26')"
        )
        self.assertIn("globalIn(key,", sql)
        self.assertIn(self._group_0_column(), sql)

    @parameterized.expand(
        [
            ("two_groups", "SELECT group_0.properties, group_1.properties FROM events WHERE {bound}", 2),
            ("session_and_group", "SELECT session.$entry_current_url, group_0.properties FROM events WHERE {bound}", 1),
            ("select_alias", "SELECT event AS name, group_0.properties FROM events WHERE {bound} AND name = 'x'", 0),
            (
                "array_join_alias",
                "SELECT group_0.properties FROM events ARRAY JOIN [1, 2] AS item WHERE {bound} AND item = 1",
                0,
            ),
            (
                "aliased_from",
                "SELECT group_0.properties FROM events AS e WHERE e.timestamp > toDateTime('2026-01-01')",
                1,
            ),
            ("physical_group_alias", "SELECT group_0.properties FROM events WHERE {bound} AND {group_0}", 1),
            ("group_type_name_alias", "SELECT group_0.properties FROM events WHERE {bound} AND {company}", 1),
            ("person_lazy_join", "SELECT group_0.properties FROM events WHERE {bound} AND {person}", 1),
            (
                "qualified_physical_group_alias",
                "SELECT group_0.properties FROM events WHERE {bound} AND events.{group_0}",
                1,
            ),
            (
                "qualified_group_type_name_alias",
                "SELECT group_0.properties FROM events WHERE {bound} AND events.{company}",
                1,
            ),
            (
                "qualified_person_lazy_join",
                "SELECT group_0.properties FROM events WHERE {bound} AND events.{person}",
                1,
            ),
            (
                "alias_qualified_lazy_joins",
                "SELECT count() FROM events AS e WHERE e.{bound} AND e.{group_0} AND e.{person}",
                1,
            ),
            (
                "lazy_join_in_nested_and",
                "SELECT group_0.properties FROM events WHERE {bound} AND ({group_0} AND event = 'x')",
                1,
            ),
            (
                "dotted_spelling_of_an_alias",
                "SELECT e__x.group_0.properties FROM events AS e__x WHERE e__x.{bound} AND e.x.{group_0}",
                1,
            ),
            ("lazy_join_below_or", "SELECT group_0.properties FROM events WHERE {bound} OR {group_0}", 0),
            (
                "subquery_with_its_own_group_join",
                "SELECT e.group_0.properties FROM events AS e "
                "WHERE e.{bound} AND e.event IN (SELECT s.group_0.properties.name FROM events AS s)",
                1,
            ),
            ("only_lazy_join_terms", "SELECT group_0.properties FROM events WHERE {group_0} AND {person}", 0),
        ]
    )
    def test_bounds_each_group_join_whose_key_subquery_can_reuse_the_where(
        self, _name: str, query: str, expected_bounds: int
    ):
        sql = self._print(
            query.format(
                bound="timestamp > toDateTime('2026-01-01')",
                group_0="group_0.properties.industry = 'tech'",
                company="company.properties.industry = 'tech'",
                person="person.properties.plan = 'pro'",
            )
        )
        self.assertEqual(sql.count("globalIn(key,"), expected_bounds)

    def test_key_subquery_leaves_out_a_term_that_differs_on_each_read(self):
        sql = self._print(
            "SELECT group_0.properties FROM events WHERE timestamp > toDateTime('2026-01-01') AND rand() % 2 = 0"
        )
        self.assertEqual(sql.count("globalIn(key,"), 1)
        self.assertEqual(sql.count("rand()"), 1)

    def test_group_type_named_like_the_table_is_not_a_qualifier_under_an_alias(self):
        create_group_type_mapping(
            team=self.team,
            project=self.team.project,
            group_type="events",
            group_type_index=2,
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        invalidate_group_types_cache(self.team.project_id)
        self.context = HogQLContext(
            team=self.team, database=Database.create_for(team=self.team), enable_select_queries=True
        )
        sql = self._print(
            "SELECT e.group_0.properties FROM events AS e "
            "WHERE e.timestamp > toDateTime('2026-01-01') AND events.properties.industry = 'tech'"
        )
        self.assertEqual(sql.count("globalIn(key,"), 2)

    def test_skips_filter_when_outer_where_lacks_timestamp(self):
        # No timestamp reference → the optimization would push a key subquery that scans every
        # event for the team, which is strictly worse than no filter. Guard skips it.
        sql = self._print("SELECT group_0.properties FROM events WHERE event = '$pageview'")
        self.assertNotIn("globalIn(key,", sql)

    def test_skips_filter_when_outer_has_no_where(self):
        sql = self._print("SELECT group_0.properties FROM events")
        self.assertNotIn("globalIn(key,", sql)
