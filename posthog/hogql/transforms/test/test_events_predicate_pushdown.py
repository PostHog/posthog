import re
import json
from typing import Any, cast
from uuid import uuid4

import pytest
from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    materialized,
)
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    HogQLQueryModifiers,
    InCohortVia,
    InlineCohortCalculation,
    PersonsOnEventsMode,
    PropertyGroupsMode,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import IntegerDatabaseField, SavedQuery, StringDatabaseField, TableNode
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import EventsPredicatePushdownExtractor
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.resolver import resolve_types
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.hogql.transforms.events_predicate_pushdown import (
    EventsPredicatePushdownTransform,
    EventsSubexprHoister,
    _printer_top_level_select_ids,
)
from posthog.hogql.transforms.logical_property_lowering import lower_property_access
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.client import sync_execute
from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition
from posthog.models.utils import uuid7

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import recalculate_cohortpeople
from products.event_definitions.backend.models.property_definition import PropertyType


class TestEventsPredicatePushdownTransform(BaseTest):
    snapshot: Any
    maxDiff = None

    def _events_table_ref(self) -> str:
        return "events_json" if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA else "events"

    def _events_schema_snapshot(self):
        self.snapshot.session.pytest_session.config.option.warn_unused_snapshots = True
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            return self.snapshot(name="new_events_schema")
        return self.snapshot

    def _print_select(self, select: str, modifiers: HogQLQueryModifiers | None = None):
        expr = parse_select(select)
        query, _ = prepare_and_print_ast(
            expr,
            HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=modifiers if modifiers is not None else HogQLQueryModifiers(pushDownPredicates=True),
            ),
            "clickhouse",
        )
        return pretty_print_in_tests(query, self.team.pk)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_with_session_join_and_timestamp_filter(self):
        """Pushes timestamp filter into subquery when events table has lazy session join."""
        printed = self._print_select(
            "SELECT event, session.$session_duration FROM events WHERE timestamp >= '2024-01-01'"
        )
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_with_alias_and_session_join(self):
        """Preserves events table alias in the subquery wrapper."""
        printed = self._print_select(
            "SELECT e.event, session.$session_duration FROM events AS e WHERE e.timestamp >= '2024-01-01'"
        )
        assert printed == self._events_schema_snapshot()

    def test_aliased_events_pushdown_subquery_defines_its_own_alias(self):
        # When the events table is aliased (FROM events AS e), the pushed predicate keeps referencing `e`.
        # Rather than rewrite every reference to the inner table (fragile: the printer renders a field from
        # its resolved type, not its chain, so a materialized property still leaked `e.mat_*`), the inner
        # subquery keeps the same alias on its own FROM (`FROM events AS e`), so `e.timestamp` resolves there.
        printed = self._print_select(
            "SELECT e.event, session.$session_duration FROM events AS e WHERE e.timestamp >= '2024-01-01'"
        )

        # Isolate the pushed-down events subquery: `FROM ( <subquery> ) AS e LEFT JOIN ...`
        assert "FROM (" in printed and ") AS e LEFT JOIN" in printed, printed
        events_subquery = printed.split("FROM (", 1)[1].split(") AS e LEFT JOIN", 1)[0]

        # The subquery aliases its own events scan as `e`, so the pushed `e.timestamp` predicate resolves
        # against it, not the out-of-scope outer alias.
        assert f"FROM {self._events_table_ref()} AS e" in events_subquery, (
            "expected the inner subquery to alias events as `e` so pushed `e.*` predicates resolve:\n" + events_subquery
        )
        assert "e.timestamp" in events_subquery, (
            "expected the pushed-down predicate to reference the inner `e`-aliased events table:\n" + events_subquery
        )

    def test_unexpected_internal_error_degrades_to_flat_query(self):
        # Pushdown is a pure optimization: an unexpected raise inside the rewrite must leave the query intact
        # (run flat), never break it. Force a raise in _build_subquery (called before any mutation) and
        # assert the printed SQL matches the un-pushed flat form.
        select = "SELECT event, session.$session_duration FROM events WHERE timestamp >= '2024-01-01' LIMIT 10"
        flat = self._print_select(select, modifiers=HogQLQueryModifiers(pushDownPredicates=False))
        with patch.object(EventsPredicatePushdownTransform, "_build_subquery", side_effect=RuntimeError("boom")):
            guarded = self._print_select(select, modifiers=HogQLQueryModifiers(pushDownPredicates=True))
        assert guarded == flat, f"expected flat fallback on internal error:\nflat={flat}\nguarded={guarded}"
        assert ") AS events LEFT JOIN" not in guarded, f"the events scan must not be wrapped on fallback:\n{guarded}"

    def test_restricted_property_still_stripped_after_pushdown(self):
        # Property-level access control strips a restricted event property from the raw `properties` blob via
        # JSONDropKeys. Pushdown exposes that blob inside the events subquery, so the stripping must apply there
        # too (the subquery's events scan keeps its EventsTable type). Pin it on both the pushed and flat forms.
        select = (
            "SELECT properties, session.$session_duration AS d FROM events WHERE timestamp >= '2024-01-01' LIMIT 10"
        )

        def _print(push_down: bool) -> str:
            context = HogQLContext(
                team_id=self.team.pk,
                enable_select_queries=True,
                modifiers=HogQLQueryModifiers(pushDownPredicates=push_down),
            )
            context.restricted_properties = {("email", PropertyDefinition.Type.EVENT)}
            query, _ = prepare_and_print_ast(parse_select(select), context, "clickhouse")
            return pretty_print_in_tests(query, self.team.pk)

        flat = _print(False)
        assert "JSONDropKeys" in flat, f"expected the restricted key stripped in the flat query:\n{flat}"
        pushed = _print(True)
        assert ") AS events LEFT JOIN" in pushed, f"expected pushdown to fire:\n{pushed}"
        events_subquery = pushed.split("FROM (", 1)[1].split(") AS events LEFT JOIN", 1)[0]
        assert "JSONDropKeys" in events_subquery, (
            "pushdown must preserve restricted-key stripping on the inner events scan:\n" + events_subquery
        )

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_without_join_no_pushdown(self):
        """No pushdown when there are no lazy joins."""
        printed = self._print_select("SELECT event FROM events WHERE timestamp >= '2024-01-01'")
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_without_where_no_pushdown(self):
        """No pushdown when there is no WHERE clause."""
        printed = self._print_select("SELECT event, session.$session_duration FROM events")
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_session_duration_filter_declines(self):
        """A session-duration predicate is residual (can't be pushed into the events subquery), so the whole
        pushdown declines and the query runs flat with the predicate in the outer WHERE."""
        printed = self._print_select(
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND session.$session_duration > 0"
        )
        assert ") AS events LEFT JOIN" not in printed, printed
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_multiple_pushable_predicates(self):
        """Multiple events-table predicates can be pushed down together."""
        printed = self._print_select(
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND event = '$pageview'"
        )
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_subquery_with_pushdown(self):
        """Subquery pushdown"""
        # The inner subquery is nested (not outermost), so it needs its own explicit LIMIT to be pushed;
        # the outer aggregate (avg + GROUP BY) is correctly left un-pushed.
        printed = self._print_select(
            "SELECT event, avg($session_duration) FROM ("
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND (event = '$pageview' OR event = '$pageleave') "
            "LIMIT 100"
            ") GROUP BY event"
        )
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_simple_events_with_person_join(self):
        printed = self._print_select(
            "SELECT event, person.id FROM events WHERE timestamp > '2024-01-01'",
        )
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_poe_properties_with_session_join(self):
        """VirtualTable field poe.properties is included in subquery as person_properties."""
        printed = self._print_select(
            "SELECT event, poe.properties, session.$session_duration FROM events WHERE timestamp >= '2024-01-01'"
        )
        assert ") AS events LEFT JOIN" in printed, printed
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_poe_id_with_session_join(self):
        """VirtualTable field poe.id is included in subquery as person_id."""
        printed = self._print_select(
            "SELECT poe.id, session.$session_duration FROM events WHERE timestamp >= '2024-01-01'"
        )
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_poe_created_at_with_session_join(self):
        """VirtualTable field poe.created_at is included in subquery as person_created_at."""
        printed = self._print_select(
            "SELECT event, poe.created_at, session.$session_duration FROM events WHERE timestamp >= '2024-01-01'"
        )
        assert ") AS events LEFT JOIN" in printed, printed
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_multiple_poe_fields_with_session_join(self):
        """Multiple VirtualTable fields are all included in the subquery."""
        printed = self._print_select(
            "SELECT event, poe.id, poe.properties, poe.created_at, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01'"
        )
        assert ") AS events LEFT JOIN" in printed, printed
        assert printed == self._events_schema_snapshot()

    # Only LEFT [OUTER] joins preserve every events row, so only they let the pushed inner LIMIT stay
    # result-equivalent and push. INNER / CROSS can drop an events row, and RIGHT / FULL can synthesize null
    # events rows, so both groups decline under the single-rule gate (no safe inner LIMIT). Join types within
    # each group differ only in the keyword, so they share one parameterized snapshot test.
    _ROW_PRESERVING_JOINS = [
        ("left_join", "LEFT JOIN sessions ON events.$session_id = sessions.session_id"),
        ("left_outer_join", "LEFT OUTER JOIN sessions ON events.$session_id = sessions.session_id"),
    ]
    _NON_ROW_PRESERVING_JOINS = [
        ("explicit_join", "JOIN sessions ON events.$session_id = sessions.session_id"),
        ("inner_join", "INNER JOIN sessions ON events.$session_id = sessions.session_id"),
        ("cross_join", "CROSS JOIN sessions"),
        ("right_join", "RIGHT JOIN sessions ON events.$session_id = sessions.session_id"),
        ("right_outer_join", "RIGHT OUTER JOIN sessions ON events.$session_id = sessions.session_id"),
        ("full_outer_join", "FULL OUTER JOIN sessions ON events.$session_id = sessions.session_id"),
        ("full_join", "FULL JOIN sessions ON events.$session_id = sessions.session_id"),
    ]

    @parameterized.expand(_ROW_PRESERVING_JOINS)
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_row_preserving_join_pushes_timestamp_down(self, _name: str, join_clause: str):
        """LEFT [OUTER] joins preserve every events row, so the inner LIMIT stays equivalent and the
        events.timestamp predicate is pushed into the subquery."""
        printed = self._print_select(
            f"SELECT sessions.session_id, uuid FROM events {join_clause} WHERE events.timestamp > '2021-01-01'"
        )
        assert ") AS events LEFT" in printed, f"{_name} should push the predicate into a subquery:\n{printed}"
        assert printed == self._events_schema_snapshot()

    @parameterized.expand(_NON_ROW_PRESERVING_JOINS)
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_non_row_preserving_join_skips_pushdown(self, _name: str, join_clause: str):
        """INNER / CROSS can drop an events row and RIGHT / FULL can synthesize null events rows, so the
        pushed inner LIMIT would change results; the pushdown declines and the query runs flat."""
        printed = self._print_select(
            f"SELECT sessions.session_id, uuid FROM events {join_clause} WHERE events.timestamp > '2021-01-01'"
        )
        assert ") AS events LEFT JOIN" not in printed, f"{_name} should not push the predicate:\n{printed}"
        assert printed == self._events_schema_snapshot()

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_bare_timestamp_with_select_alias_pushes_down(self):
        printed = self._print_select(
            "SELECT event, toTimeZone(timestamp, 'UTC') as timestamp, session.$session_duration "
            "FROM events "
            "WHERE timestamp >= '2024-01-01' AND timestamp <= today()"
        )
        assert printed == self._events_schema_snapshot()

    def test_non_pushable_prewhere_bails(self):
        # A PREWHERE with a non-events (joined) predicate can't be pushed, and can't stay on the outer query
        # either: after pushdown the outer FROM is a subquery, where PREWHERE is invalid. So the transform
        # bails rather than emit an invalid PREWHERE on a subquery. (Such a query is already invalid ClickHouse
        # since PREWHERE can't reference a joined column, so this just guarantees we don't make it worse.)
        printed = self._print_select(
            "SELECT event, session.$session_duration FROM events "
            "PREWHERE timestamp >= '2024-01-01' AND session.$session_duration > 0"
        )
        assert ") AS events LEFT JOIN" not in printed, (
            "expected pushdown to bail on a non-pushable PREWHERE:\n" + printed
        )

    def test_pushable_prewhere_and_where_both_pushed(self):
        # An events-only PREWHERE and an events-only WHERE are both pushable. The PREWHERE stays a PREWHERE on
        # the inner events scan (honoring intent), the WHERE goes to the inner WHERE, and no PREWHERE remains
        # on the outer subquery-based query (where it would be invalid).
        printed = self._print_select(
            "SELECT event, session.$session_duration FROM events PREWHERE event = '$pageview' WHERE timestamp >= '2024-01-01'"
        )
        # Compact all whitespace so the structural assertions don't depend on pretty-printer line breaks.
        compact = "".join(printed.split())
        assert ")ASeventsLEFTJOIN" in compact, "expected pushdown to fire:\n" + printed
        subquery = compact.split("FROM(", 1)[1].split(")ASeventsLEFTJOIN", 1)[0]
        assert "PREWHERE" in subquery, "pushed PREWHERE should stay a PREWHERE on the inner events scan:\n" + printed
        assert "equals(events.event" in subquery, "PREWHERE predicate should be on the inner scan:\n" + printed
        assert "greaterOrEquals(events.timestamp" in subquery, (
            "WHERE predicate should be pushed into the subquery:\n" + printed
        )
        assert "PREWHERE" not in compact.split(")ASeventsLEFTJOIN", 1)[1], (
            "no PREWHERE should remain on the subquery-based outer query:\n" + printed
        )

    # Gate: pushdown only helps when the LIMIT can short-circuit the events scan. Aggregate / GROUP BY /
    # DISTINCT / window all consume the whole filtered set before the LIMIT applies, so the pre-filter
    # subquery would be pure materialization overhead; decline (still correct, just not worth it).
    _FORCES_FULL_READ_SHAPES = [
        (
            "aggregate_fn",
            "SELECT count() AS c, max(session.$session_duration) AS d FROM events WHERE timestamp >= '2024-01-01'",
        ),
        (
            "group_by",
            "SELECT event, count() AS c FROM events WHERE timestamp >= '2024-01-01' AND session.$session_duration > 0 GROUP BY event",
        ),
        ("distinct", "SELECT DISTINCT event, session.$session_duration FROM events WHERE timestamp >= '2024-01-01'"),
        (
            "window_fn",
            "SELECT event, row_number() OVER (ORDER BY timestamp) AS rn, session.$session_duration FROM events WHERE timestamp >= '2024-01-01'",
        ),
    ]

    @parameterized.expand(_FORCES_FULL_READ_SHAPES)
    def test_full_event_read_shapes_are_not_pushed(self, _name: str, select: str):
        printed = self._print_select(select)
        assert ") AS events LEFT JOIN" not in printed, f"{_name} should not be pushed (full-read shape):\n{printed}"

    def test_nested_subquery_without_limit_is_not_pushed(self):
        # A nested events subquery gets no auto-limit, and without an explicit one its LIMIT can't
        # short-circuit the events scan, so we decline.
        printed = self._print_select(
            "SELECT event, d FROM ("
            "SELECT event, session.$session_duration AS d FROM events WHERE timestamp >= '2024-01-01'"
            ") LIMIT 100"
        )
        assert ") AS events LEFT JOIN" not in printed, (
            "nested subquery without a LIMIT should not be pushed:\n" + printed
        )

    def test_nested_subquery_with_explicit_limit_is_pushed(self):
        # The same nested subquery with its own LIMIT can short-circuit, so it is pushed.
        printed = self._print_select(
            "SELECT event, d FROM ("
            "SELECT event, session.$session_duration AS d FROM events WHERE timestamp >= '2024-01-01' LIMIT 100"
            ")"
        )
        assert ") AS events LEFT JOIN" in printed, (
            "nested subquery with an explicit LIMIT should be pushed:\n" + printed
        )

    def test_pushdown_array_index_vs_object_key_stay_distinct(self):
        # `properties.a[1]` (array index) and `properties.a['1']` (object key) are different extractions that share
        # one preferred name (`properties__a__1`); they must hoist to separate projections, or the second read
        # silently returns the first's value.
        printed = self._print_select(
            "SELECT properties.a[1] AS i, properties.a['1'] AS k, session.$session_duration "
            "FROM events WHERE timestamp >= '2024-01-01' LIMIT 10"
        )
        assert ") AS events LEFT JOIN" in printed, f"expected pushdown to fire:\n{printed}"
        match_i = re.search(r"SELECT (.*?) AS i,", printed)
        match_k = re.search(r" AS i, (.*?) AS k,", printed)
        assert match_i and match_k, printed
        assert match_i.group(1) != match_k.group(1), f"distinct reads collapsed onto one projection:\n{printed}"

    def test_pushdown_nested_key_vs_flat_double_underscore_key_stay_distinct(self):
        # Nested `properties.a.b` and a flat property literally named `a__b` share the preferred name
        # `properties__a__b` but are different reads; they must hoist to separate projections.
        printed = self._print_select(
            "SELECT properties.a.b AS x, properties['a__b'] AS y, session.$session_duration "
            "FROM events WHERE timestamp >= '2024-01-01' LIMIT 10"
        )
        assert ") AS events LEFT JOIN" in printed, f"expected pushdown to fire:\n{printed}"
        match_x = re.search(r"SELECT (.*?) AS x,", printed)
        match_y = re.search(r" AS x, (.*?) AS y,", printed)
        assert match_x and match_y, printed
        assert match_x.group(1) != match_y.group(1), f"distinct reads collapsed onto one projection:\n{printed}"


class TestOuterWhereAssignment:
    """Verify that _apply_pushdown assigns outer_where back to node.where."""

    def test_extractor_correctly_splits_mixed_predicates(self):
        timestamp_pred = ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value="2024-01-01"),
        )
        session_pred = ast.CompareOperation(
            op=ast.CompareOperationOp.Gt,
            left=ast.Field(chain=["events__session", "duration"]),
            right=ast.Constant(value=0),
        )
        where = ast.And(exprs=[timestamp_pred, session_pred])

        extractor = EventsPredicatePushdownExtractor(joined_table_aliases={"events__session"})
        inner_where, outer_where = extractor.get_pushdown_predicates(where)

        assert inner_where is not None
        assert outer_where is not None


class TestEventsPredicatePushdownTransformUnit:
    """Unit tests for helper methods that don't require database/context."""

    def _make_events_select_with_join(
        self, where_clause: ast.Expr | None = None, alias: str | None = None, sample: ast.SampleExpr | None = None
    ) -> ast.SelectQuery:
        """Create a minimal SELECT query from events with a join for testing."""
        events_field = ast.Field(chain=["events"])

        mock_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=ast.SelectQuery(
                select=[ast.Field(chain=["*"])],
                select_from=ast.JoinExpr(table=ast.Field(chain=["sessions"])),
            ),
            alias="events__session",
        )

        select_from = ast.JoinExpr(
            table=events_field,
            alias=alias,
            next_join=mock_join,
            sample=sample,
            # _should_apply_pushdown now keys off the resolved table type (it runs post-resolution),
            # so the FROM must carry the events TableType for these unit tests.
            type=ast.TableType(table=EventsTable()),
        )

        return ast.SelectQuery(
            select=[ast.Field(chain=["event"])],
            select_from=select_from,
            where=where_clause,
            # The gate requires an effective LIMIT (so the LIMIT can short-circuit the events scan); give the
            # node an explicit one. Tests asserting decline fail on their own check (no WHERE, SAMPLE, etc.).
            limit=ast.Constant(value=100),
        )

    def test_printer_top_level_select_ids_excludes_nested_union_branches(self):
        # The printer injects a top-level LIMIT only on the root select or the direct branches of the
        # OUTERMOST union (depth 2). A nested-union inner branch sits deeper, so it must be excluded; else it
        # would get an inner LIMIT with no matching printer-injected outer cap, diverging from the flat query.
        a, b, c = (parse_select("SELECT event FROM events") for _ in range(3))
        assert isinstance(a, ast.SelectQuery) and isinstance(b, ast.SelectQuery) and isinstance(c, ast.SelectQuery)

        assert _printer_top_level_select_ids(a) == {id(a)}, "a root SelectQuery is itself top-level"

        simple = ast.SelectSetQuery.create_from_queries([a, b], "UNION ALL")
        assert _printer_top_level_select_ids(simple) == {id(a), id(b)}, "both direct branches of a union are top-level"

        inner = ast.SelectSetQuery.create_from_queries([a, b], "UNION ALL")
        nested = ast.SelectSetQuery.create_from_queries([inner, c], "UNION ALL")
        assert _printer_top_level_select_ids(nested) == {id(c)}, (
            "only the outermost direct SelectQuery branch is top-level"
        )

    def test_should_apply_pushdown_with_valid_query(self):
        where_clause = ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value="2024-01-01"),
        )
        node = self._make_events_select_with_join(where_clause=where_clause)

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        assert transform._should_apply_pushdown(node) is True

    def test_should_not_apply_pushdown_without_where(self):
        node = self._make_events_select_with_join(where_clause=None)

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        assert transform._should_apply_pushdown(node) is False

    def test_should_not_apply_pushdown_without_joins(self):
        events_field = ast.Field(chain=["events"])
        select_from = ast.JoinExpr(table=events_field, next_join=None)
        node = ast.SelectQuery(
            select=[ast.Field(chain=["event"])],
            select_from=select_from,
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value="2024-01-01"),
            ),
        )

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        assert transform._should_apply_pushdown(node) is False

    def test_should_not_apply_pushdown_for_non_events_table(self):
        persons_field = ast.Field(chain=["persons"])
        mock_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=ast.Field(chain=["other"]),
            alias="other_alias",
        )
        select_from = ast.JoinExpr(table=persons_field, next_join=mock_join)
        node = ast.SelectQuery(
            select=[ast.Field(chain=["id"])],
            select_from=select_from,
            where=ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["created_at"]),
                right=ast.Constant(value="2024-01-01"),
            ),
        )

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        assert transform._should_apply_pushdown(node) is False

    def test_should_apply_pushdown_with_prewhere_instead_of_where(self):
        """Bug: queries with PREWHERE but no WHERE skip pushdown entirely."""
        prewhere = ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value="2024-01-01"),
        )
        node = self._make_events_select_with_join(where_clause=None)
        node.prewhere = prewhere

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        assert transform._should_apply_pushdown(node) is True

    def test_should_not_apply_pushdown_with_sample_clause(self):
        sample = ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=10)))
        where_clause = ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value="2024-01-01"),
        )
        node = self._make_events_select_with_join(where_clause=where_clause, sample=sample)

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        assert transform._should_apply_pushdown(node) is False

    _TS_PRED = ast.CompareOperation(
        op=ast.CompareOperationOp.GtEq,
        left=ast.Field(chain=["timestamp"]),
        right=ast.Constant(value="2024-01-01"),
    )

    def test_should_not_apply_pushdown_without_effective_limit(self):
        # No explicit LIMIT and not an outermost select → nothing for the pushdown to short-circuit, decline.
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        node.limit = None

        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))

        assert transform._should_apply_pushdown(node) is False

    def test_should_apply_pushdown_for_top_level_without_explicit_limit(self):
        # An outermost select gets a top-level LIMIT injected later, so it counts as limited even with no
        # LIMIT on the AST yet (the auto-limit mechanism the gate relies on).
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        node.limit = None

        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1), top_level_select_ids={id(node)})

        assert transform._should_apply_pushdown(node) is True

    def test_should_not_apply_pushdown_with_aggregate_nested_in_call(self):
        # The aggregate is wrapped in a non-aggregate call, so the blocker finder must recurse into call args
        # to detect it; otherwise the whole-set read would be missed and the subquery wasted.
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        node.select = [
            ast.Call(
                name="round", args=[ast.Call(name="avg", args=[ast.Field(chain=["timestamp"])]), ast.Constant(value=2)]
            )
        ]

        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))

        assert transform._should_apply_pushdown(node) is False

    def test_should_not_apply_pushdown_with_aggregate_only_in_having(self):
        # An aggregate reachable only via HAVING still consumes the whole filtered set before the LIMIT.
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        node.having = ast.CompareOperation(
            op=ast.CompareOperationOp.Gt, left=ast.Call(name="count", args=[]), right=ast.Constant(value=0)
        )

        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))

        assert transform._should_apply_pushdown(node) is False

    def test_should_apply_pushdown_ignoring_aggregate_in_scalar_subquery(self):
        # An aggregate inside a scalar subquery in the SELECT list belongs to that subquery's scope, not this
        # one, so it must NOT make this (non-aggregate) query decline, or we'd lose the optimization.
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        scalar_subquery = ast.SelectQuery(
            select=[ast.Call(name="count", args=[])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        )
        node.select = [ast.Field(chain=["event"]), scalar_subquery]

        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))

        assert transform._should_apply_pushdown(node) is True

    def test_should_not_apply_pushdown_when_top_level_limit_disabled(self):
        # COHORT_CALCULATION / SAVED_QUERY / exports set limit_top_select=False and inject only a huge
        # sentinel limit, nothing for the LIMIT to short-circuit, so decline even though node.limit is set.
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        context = HogQLContext(team_id=1)
        context.limit_top_select = False

        transform = EventsPredicatePushdownTransform(context)

        assert transform._should_apply_pushdown(node) is False

    def test_should_not_apply_pushdown_with_aggregate_in_order_by(self):
        # A bare aggregate in ORDER BY (no GROUP BY) is an implicit whole-set read, so the LIMIT can't
        # short-circuit; decline.
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        node.order_by = [ast.OrderExpr(expr=ast.Call(name="count", args=[]), order="DESC")]

        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))

        assert transform._should_apply_pushdown(node) is False

    def test_should_not_apply_pushdown_with_aggregate_in_qualify(self):
        # An aggregate/window reachable only via QUALIFY also forces a whole-set read.
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        node.qualify = ast.CompareOperation(
            op=ast.CompareOperationOp.Gt, left=ast.Call(name="count", args=[]), right=ast.Constant(value=0)
        )

        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))

        assert transform._should_apply_pushdown(node) is False

    def test_should_not_apply_pushdown_with_aggregate_in_call_filter(self):
        # An aggregate hidden in a non-arg call position (here filter_expr of a non-aggregate call) must still
        # be detected: the finder recurses into every child position, not just args.
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        node.select = [
            ast.Call(name="toString", args=[ast.Field(chain=["event"])], filter_expr=ast.Call(name="count", args=[]))
        ]

        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))

        assert transform._should_apply_pushdown(node) is False

    def test_safe_inner_limit_for_safe_left_join_query(self):
        # No ORDER BY, no residual predicate, LEFT join, concrete LIMIT -> push the limit (offset 0).
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))
        result = transform._safe_inner_limit(node, residual_where=None, residual_prewhere=None)
        assert isinstance(result, ast.Constant) and result.value == 100

    def test_safe_inner_limit_adds_offset(self):
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        node.offset = ast.Constant(value=20)
        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))
        result = transform._safe_inner_limit(node, None, None)
        assert isinstance(result, ast.Constant) and result.value == 120  # limit 100 + offset 20

    def test_safe_inner_limit_declines_with_order_by(self):
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        node.order_by = [ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="ASC")]
        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))
        assert transform._safe_inner_limit(node, None, None) is None

    def test_safe_inner_limit_declines_with_residual_predicate(self):
        # A predicate left on the outer query removes post-join rows, so an inner LIMIT would keep too few.
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))
        assert (
            transform._safe_inner_limit(node, residual_where=ast.Constant(value=True), residual_prewhere=None) is None
        )

    def test_safe_inner_limit_declines_for_inner_join(self):
        # An INNER join can drop an events row, so the inner LIMIT might leave fewer than `limit` rows.
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        assert node.select_from is not None and node.select_from.next_join is not None
        node.select_from.next_join.join_type = "INNER JOIN"
        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))
        assert transform._safe_inner_limit(node, None, None) is None

    def test_safe_inner_limit_declines_without_concrete_limit(self):
        # A top-level query before the executor injects a limit has no value to push.
        node = self._make_events_select_with_join(where_clause=self._TS_PRED)
        node.limit = None
        transform = EventsPredicatePushdownTransform(HogQLContext(team_id=1))
        assert transform._safe_inner_limit(node, None, None) is None

    def test_collect_joined_aliases_single_join(self):
        node = self._make_events_select_with_join(where_clause=ast.Constant(value=True))

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        aliases = transform._collect_joined_aliases(node)

        assert aliases == {"events__session"}

    def test_collect_joined_aliases_multiple_joins(self):
        events_field = ast.Field(chain=["events"])
        third_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=ast.Field(chain=["cohorts"]),
            alias="events__cohort",
        )
        second_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=ast.Field(chain=["persons"]),
            alias="events__person",
            next_join=third_join,
        )
        first_join = ast.JoinExpr(
            join_type="LEFT JOIN",
            table=ast.Field(chain=["sessions"]),
            alias="events__session",
            next_join=second_join,
        )
        select_from = ast.JoinExpr(table=events_field, next_join=first_join)
        node = ast.SelectQuery(
            select=[ast.Field(chain=["event"])],
            select_from=select_from,
            where=ast.Constant(value=True),
        )

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        aliases = transform._collect_joined_aliases(node)

        assert aliases == {"events__session", "events__person", "events__cohort"}

    @pytest.mark.parametrize(
        "join_type",
        ["RIGHT JOIN", "RIGHT OUTER JOIN", "FULL JOIN", "FULL OUTER JOIN"],
    )
    def test_collect_joined_aliases_empty_for_unsafe_join_type(self, join_type: str):
        events_field = ast.Field(chain=["events"])
        mock_join = ast.JoinExpr(
            join_type=join_type,
            table=ast.Field(chain=["sessions"]),
            alias="events__session",
        )
        select_from = ast.JoinExpr(table=events_field, next_join=mock_join)
        node = ast.SelectQuery(
            select=[ast.Field(chain=["event"])],
            select_from=select_from,
            where=ast.Constant(value=True),
        )

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        assert transform._collect_joined_aliases(node) == set()

    def test_collect_joined_aliases_empty_when_no_joins(self):
        events_field = ast.Field(chain=["events"])
        select_from = ast.JoinExpr(table=events_field, next_join=None)
        node = ast.SelectQuery(
            select=[ast.Field(chain=["event"])],
            select_from=select_from,
            where=ast.Constant(value=True),
        )

        context = HogQLContext(team_id=1)
        transform = EventsPredicatePushdownTransform(context)

        aliases = transform._collect_joined_aliases(node)
        assert aliases == set()


class TestEventsSubexprHoister(BaseTest):
    """The hoister rewrites an events query's outer leaves into references to the pre-filtering subquery, recording
    which columns / property values the subquery must project. It runs on the lowered AST (property value reads are
    `PropertyAccess`); a lazy-join or other non-events reference is simply left in the outer query."""

    def setUp(self):
        super().setUp()
        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team_id=self.team.pk, database=self.database, enable_select_queries=True)

    def _run(self, query: str) -> tuple[EventsSubexprHoister, list[ast.Expr], ast.SelectQueryAliasType]:
        resolved = resolve_types(parse_select(query), self.context, dialect="clickhouse")
        lowered = lower_property_access(resolved, self.context)
        assert isinstance(lowered, ast.SelectQuery) and lowered.select_from is not None
        from_type = lowered.select_from.type
        assert isinstance(from_type, (ast.TableType, ast.TableAliasType))
        subquery_ref = ast.SelectQueryAliasType(
            alias="events", select_query_type=ast.SelectQueryType(columns={}, tables={})
        )
        hoister = EventsSubexprHoister(from_type, subquery_ref, self.context)
        rewritten = [cast(ast.Expr, hoister.visit(item)) for item in lowered.select]
        return hoister, rewritten, subquery_ref

    @staticmethod
    def _references_subquery(node: ast.Expr, subquery_ref: ast.SelectQueryAliasType) -> bool:
        found = False

        class _Finder(TraversingVisitor):
            def visit_field(self, n: ast.Field) -> None:
                nonlocal found
                if isinstance(n.type, ast.FieldType) and n.type.table_type is subquery_ref:
                    found = True
                super().visit_field(n)

        _Finder().visit(node)
        return found

    def test_direct_columns_are_projected(self):
        hoister, _, _ = self._run("SELECT event, timestamp FROM events WHERE distinct_id = 'u1'")
        assert {"event", "timestamp"} <= set(hoister.projections)
        assert hoister.blocked is False

    def test_direct_column_is_projected_under_its_database_name(self):
        # A direct column is hoisted under its database name and the outer occurrence reads the subquery column;
        # the printer resolves its nullability through the subquery column type, so it stays a usable join key.
        hoister, rewritten, subquery_ref = self._run("SELECT event FROM events")
        assert "event" in hoister.projections
        assert self._references_subquery(rewritten[0], subquery_ref) is True

    def test_property_is_projected_under_its_dunder_name(self):
        # The name is `<blob column>__<key>`, so reads off different blobs never collide on a bare key.
        hoister, _, _ = self._run("SELECT properties.$browser FROM events")
        assert "properties__$browser" in hoister.projections
        assert hoister.blocked is False

    def test_nested_property_uses_dunder_joined_name(self):
        hoister, _, _ = self._run("SELECT properties.a.b FROM events")
        assert "properties__a__b" in hoister.projections

    def test_property_reference_is_rewritten_to_subquery(self):
        # The outer occurrence of a property read becomes a reference to the subquery column the physical pass fills.
        _, rewritten, subquery_ref = self._run("SELECT properties.$browser FROM events")
        assert self._references_subquery(rewritten[0], subquery_ref) is True

    def test_joined_table_field_is_not_projected(self):
        # session.* is a lazy join, never the target events table; the hoister leaves it for the outer query.
        hoister, _, _ = self._run("SELECT event FROM events")
        assert "session_duration" not in hoister.projections and "$session_duration" not in hoister.projections

    def test_poe_properties_collected_as_person_properties(self):
        # poe.properties (VirtualTable) resolves to database column person_properties.
        hoister, _, _ = self._run("SELECT poe.properties FROM events")
        assert "person_properties" in hoister.projections
        assert hoister.blocked is False

    def test_poe_id_collected_as_person_id(self):
        # poe.id (VirtualTable) resolves to database column person_id.
        hoister, _, _ = self._run("SELECT poe.id FROM events")
        assert "person_id" in hoister.projections
        assert hoister.blocked is False

    def test_poe_created_at_collected_as_person_created_at(self):
        # poe.created_at (VirtualTable) resolves to database column person_created_at.
        hoister, _, _ = self._run("SELECT poe.created_at FROM events")
        assert "person_created_at" in hoister.projections
        assert hoister.blocked is False

    def test_poe_field_type_has_virtual_table_type(self):
        # The projected poe field keeps its VirtualTableType (the physical pass peels it to person_properties).
        hoister, _, _ = self._run("SELECT poe.properties FROM events")
        field_type = hoister.column_types["person_properties"]
        assert isinstance(field_type, ast.FieldType)
        assert isinstance(field_type.table_type, ast.VirtualTableType)

    def test_poe_mixed_with_direct_columns(self):
        # VirtualTable fields and direct columns are both projected.
        hoister, _, _ = self._run("SELECT event, poe.id, timestamp FROM events")
        assert {"event", "person_id", "timestamp"} <= set(hoister.projections)
        assert hoister.blocked is False

    def test_poe_revenue_analytics_lazy_join_triggers_non_direct(self):
        # poe.revenue_analytics is a LazyJoin inside VirtualTable, not an events column, so it is foreign — left in
        # the outer query (an empty projection set makes the full transform decline pushdown), never hoisted.
        hoister, rewritten, subquery_ref = self._run("SELECT poe.revenue_analytics.revenue FROM events")
        assert hoister.projections == {}
        assert self._references_subquery(rewritten[0], subquery_ref) is False

    def test_poe_property_and_event_property_same_key_project_separately(self):
        # `properties.url` reads the event blob; `poe.properties.url` reads `person_properties`. They share the key
        # `url` but must hoist to separate columns — collapsing them onto one silently read the wrong blob for one.
        hoister, _, _ = self._run("SELECT properties.url, poe.properties.url FROM events")
        assert "properties__url" in hoister.projections
        assert "person_properties__url" in hoister.projections
        assert hoister.blocked is False

    def test_different_reads_colliding_on_preferred_name_get_separate_projections(self):
        # `properties.a.b` and `properties['a__b']` both prefer the name `properties__a__b` but are different reads;
        # the second must get a fresh synthetic column instead of silently reusing the first's projection.
        hoister, _, _ = self._run("SELECT properties.a.b, properties['a__b'] FROM events")
        assert "properties__a__b" in hoister.projections
        assert "__pd_expr_0" in hoister.projections
        assert hoister.projections["properties__a__b"] != hoister.projections["__pd_expr_0"]

    def test_identical_computed_expressions_share_one_projection(self):
        # Structurally identical non-leaf expressions dedupe onto a single synthetic projection.
        hoister, _, _ = self._run("SELECT upper(event), upper(event) FROM events")
        synthetic = [name for name in hoister.projections if name.startswith("__pd_expr_")]
        assert len(synthetic) == 1


class TestSavedQueryWithLazyJoins(BaseTest):
    """Tests for predicate pushdown with SavedQuery views that contain lazy joins.

    A SavedQuery view's lazy joins (like events.person.distinct_id) should be fully resolved when the view is
    expanded during resolve_types, before predicate pushdown runs.
    """

    def setUp(self):
        super().setUp()
        self.database = Database.create_for(team=self.team)

        # A SavedQuery containing lazy joins, simulating what revenue_analytics views do.
        self.saved_query = SavedQuery(
            id="test_view",
            name="test_events_with_person",
            query="SELECT event, person.id AS person_id, session.$session_duration AS session_duration FROM events WHERE timestamp > '2024-01-01'",
            fields={
                "event": StringDatabaseField(name="event"),
                "person_id": StringDatabaseField(name="person_id"),
                "session_duration": IntegerDatabaseField(name="session_duration"),
            },
        )

        self.database.tables.add_child(TableNode(name="test_events_with_person", table=self.saved_query))

        self.context = HogQLContext(
            team_id=self.team.pk,
            database=self.database,
            enable_select_queries=True,
        )

    def test_saved_query_with_lazy_joins_and_session_join(self):
        """Query from SavedQuery that internally uses lazy joins should resolve properly."""

        # The persons table join needs the team on the context.
        self.context.team = self.team

        query_str = "SELECT event, person_id, session_duration FROM test_events_with_person"

        query, prepared_ast = prepare_and_print_ast(
            parse_select(query_str),
            self.context,
            "clickhouse",
        )

        # Completing without error verifies the lazy joins were fully resolved.
        assert "SELECT" in query


# Result-equivalence tests that run real ClickHouse queries. Unlike the printer tests above (which only
# assert on the generated SQL string), these create events, execute the query with pushDownPredicates on
# and off, and assert identical results: pushdown is a pure optimization, and executing the query surfaces
# any SQL ClickHouse rejects (e.g. an outer-alias leak), which string snapshots cannot catch.
class _PushdownExecutionTestBase(ClickhouseTestMixin, APIBaseTest):
    snapshot: Any
    _property_groups_mode: PropertyGroupsMode | None = None
    _pass_team = False  # Dmat slot resolution needs the team on the print context

    def _modifiers(self, *, push_down: bool) -> HogQLQueryModifiers:
        extra = {"propertyGroupsMode": self._property_groups_mode} if self._property_groups_mode is not None else {}
        return HogQLQueryModifiers(pushDownPredicates=push_down, **extra)

    def _events_table_ref(self) -> str:
        return "events_json" if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA else "events"

    def _events_schema_snapshot(self):
        self.snapshot.session.pytest_session.config.option.warn_unused_snapshots = True
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            return self.snapshot(name="new_events_schema")
        return self.snapshot

    def _assert_events_property_source(self, subquery: str, property_name: str, legacy_column: str) -> None:
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert legacy_column not in subquery, f"new events schema should not use {legacy_column}:\n{subquery}"
            assert f"events.properties.{property_name}" in subquery, (
                f"expected JSON subcolumn for {property_name}:\n{subquery}"
            )
        else:
            assert legacy_column in subquery, f"expected legacy materialized column {legacy_column}:\n{subquery}"

    def _assert_json_has_source(self, subquery: str) -> None:
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert "properties_group" not in subquery, f"new events schema should not use property groups:\n{subquery}"
            assert "JSONExtractKeysAndValuesRaw" not in subquery, (
                f"new events schema should not reconstruct JSON paths:\n{subquery}"
            )
            assert "isNotNull(events.properties.tier)" in subquery, (
                f"expected a direct JSON subcolumn existence check:\n{subquery}"
            )
        else:
            assert "properties_group" in subquery, f"expected the property-group Map column exposed:\n{subquery}"

    def _print_pushdown_sql(self, select: str) -> str:
        context = HogQLContext(
            team_id=self.team.pk,
            team=self.team if self._pass_team else None,
            enable_select_queries=True,
            modifiers=self._modifiers(push_down=True),
        )
        query, _ = prepare_and_print_ast(parse_select(select), context, "clickhouse")
        return pretty_print_in_tests(query, self.team.pk)

    def _results(self, select: str, *, push_down: bool):
        return execute_hogql_query(select, team=self.team, modifiers=self._modifiers(push_down=push_down)).results

    @staticmethod
    def _sorted(rows: list | None) -> list:
        # Sort by repr so rows with NULL columns (e.g. an unmatched LEFT JOIN's NULL duration, or a missing
        # property) don't raise on mixed None/str comparisons. Pushdown is order-agnostic with an inner LIMIT,
        # so only the multiset of rows must match on vs off.
        return sorted(rows or [], key=repr)

    def _assert_results_equivalent(self, select: str) -> list:
        with_pushdown = self._results(select, push_down=True)
        without_pushdown = self._results(select, push_down=False)
        assert self._sorted(with_pushdown) == self._sorted(without_pushdown), (
            f"pushdown changed results: on={with_pushdown} off={without_pushdown}"
        )
        return with_pushdown or []

    def _events_subquery(self, printed: str) -> str:
        assert ") AS events LEFT JOIN" in printed, f"expected pushdown to wrap events in a subquery:\n{printed}"
        return printed.split("FROM (", 1)[1].split(") AS events LEFT JOIN", 1)[0]


class TestEventsPredicatePushdownExecution(_PushdownExecutionTestBase):
    def _create_session(self, when_iso: str, distinct_id: str, tier: str, *event_timestamps: str) -> None:
        # session_id is a uuid7 whose embedded time must line up with the events so the session join matches
        session_id = str(uuid7(when_iso))
        for ts in event_timestamps:
            _create_event(
                team=self.team,
                event="watched movie",
                distinct_id=distinct_id,
                timestamp=ts,
                properties={"$session_id": session_id, "tier": tier},
            )

    def _create_data(self) -> None:
        # Two in-range sessions (Jan 2024) plus one out-of-range session (2023) the timestamp filter must drop
        self._create_session("2024-01-02T00:00:00", "u1", "pro", "2024-01-02T10:00:00", "2024-01-02T10:05:00")
        self._create_session("2024-01-05T00:00:00", "u2", "free", "2024-01-05T09:00:00")
        self._create_session("2023-06-01T00:00:00", "u3", "pro", "2023-06-01T09:00:00")
        flush_persons_and_events()

    def _assert_pushdown_equivalent(self, select: str, *, expected_rows: int) -> None:
        # Sorted comparison: the pushed inner LIMIT means queries don't need an ORDER BY (which would decline
        # the pushdown), so the row order isn't pinned; only the set of rows must match on vs off.
        with_pushdown = self._assert_results_equivalent(select)
        assert len(with_pushdown) == expected_rows, f"expected {expected_rows} rows, got {with_pushdown}"

    def test_exec_self_join_with_inner_limit_stays_equivalent(self):
        # Adversarial: a self-join shares the same `EventsTable` instance, so the column collector matches the
        # right side's columns by identity, and the right side is one-to-many on distinct_id. With the pushed
        # inner LIMIT bounding only the left scan, the full result set (LIMIT >= output) stays identical.
        self._create_data()
        select = (
            "SELECT a.event AS ae, b.event AS be FROM events AS a "
            "LEFT JOIN events AS b ON a.distinct_id = b.distinct_id "
            "WHERE a.timestamp >= '2024-01-01' AND a.timestamp < '2024-01-08' LIMIT 50"
        )
        printed = self._print_pushdown_sql(select)
        assert ") AS a LEFT JOIN" in printed, f"expected the self-join left scan to be pushed:\n{printed}"
        self._assert_results_equivalent(select)

    def test_exec_limit_below_match_count_returns_valid_rows_both_ways(self):
        # A non-ORDER-BY LIMIT smaller than the matching set is non-deterministic (even two un-pushed runs can
        # return different rows), so on==off isn't a valid assertion. The pushed inner LIMIT bounds the events
        # scan rather than the joined output, so the chosen rows can differ; assert instead that BOTH forms
        # return a valid result: exactly LIMIT rows, each drawn from the full matching set.
        for i in range(1, 7):
            self._create_session(f"2024-01-0{i}T00:00:00", f"u{i}", "pro", f"2024-01-0{i}T10:00:00")
        self._create_session("2023-06-01T00:00:00", "u_old", "pro", "2023-06-01T09:00:00")  # out of range
        flush_persons_and_events()
        base = (
            "SELECT distinct_id, session.$session_duration AS d FROM events "
            "WHERE timestamp >= '2024-01-01' AND timestamp < '2024-01-08'"
        )
        limited = base + " LIMIT 3"
        assert ") AS events LEFT JOIN" in self._print_pushdown_sql(limited), "expected the LIMIT 3 query to push"
        valid = {tuple(r) for r in (self._results(base + " LIMIT 1000", push_down=False) or [])}
        assert len(valid) == 6, f"expected 6 matching rows in the full set, got {valid}"
        for push in (True, False):
            rows = self._results(limited, push_down=push) or []
            assert len(rows) == 3, f"push={push}: expected exactly 3 rows, got {rows}"
            assert all(tuple(r) in valid for r in rows), f"push={push}: returned a row outside the matching set: {rows}"

    def test_exec_offset_with_fan_out_join_returns_valid_rows_both_ways(self):
        # OFFSET + a one-to-many LEFT join. The pushed inner LIMIT is limit + offset, so the first
        # offset+limit events still cover the outer [offset, offset+limit) slice. Below-match-count
        # LIMIT/OFFSET is non-deterministic without ORDER BY (flat too), so assert both forms return exactly
        # LIMIT rows drawn from the valid matching set, and that the inner LIMIT is limit+offset.
        self._create_data()  # u1 x2 + u2 x1 in range; self-join on distinct_id fans out (u1 -> 2 b-rows each)
        base = (
            "SELECT a.event AS ae, a.distinct_id AS aid FROM events AS a "
            "LEFT JOIN events AS b ON a.distinct_id = b.distinct_id "
            "WHERE a.timestamp >= '2024-01-01' AND a.timestamp < '2024-01-08'"
        )
        paged = base + " LIMIT 2 OFFSET 1"
        printed = self._print_pushdown_sql(paged)
        assert ") AS a LEFT JOIN" in printed, f"expected the OFFSET self-join left scan to push:\n{printed}"
        subquery = printed.split("FROM (", 1)[1].split(") AS a LEFT JOIN", 1)[0]
        assert "LIMIT 3" in subquery, f"inner LIMIT should be limit+offset (2+1=3):\n{subquery}"
        valid = {tuple(r) for r in (self._results(base + " LIMIT 1000", push_down=False) or [])}
        for push in (True, False):
            rows = self._results(paged, push_down=push) or []
            assert len(rows) == 2, f"push={push}: expected exactly 2 rows, got {rows}"
            assert all(tuple(r) in valid for r in rows), f"push={push}: returned a row outside the matching set: {rows}"

    def test_exec_binding_limit_grouped_join_returns_correct_count(self):
        # The shape that motivated the gate: events LEFT JOIN a `GROUP BY session_id` subquery, with a LIMIT
        # that actually BINDS (far more matching events than the limit, several events per session, so the
        # grouped subquery fans in). The pushed inner LIMIT must cut EVENTS before the join (not the joined
        # output), so both forms return exactly LIMIT rows from the valid set. 16 in-range events, LIMIT 5.
        self._create_session("2024-01-02T00:00:00", "u1", "pro", *[f"2024-01-02T10:{m:02d}:00" for m in range(8)])
        self._create_session("2024-01-05T00:00:00", "u2", "free", *[f"2024-01-05T11:{m:02d}:00" for m in range(8)])
        flush_persons_and_events()
        base = (
            "SELECT timestamp, session.$session_duration AS d FROM events "
            "WHERE timestamp >= '2024-01-01' AND timestamp < '2024-01-08'"
        )
        limited = base + " LIMIT 5"
        subquery = self._events_subquery(self._print_pushdown_sql(limited))
        assert "LIMIT 5" in subquery, f"expected the pushed inner LIMIT to bind:\n{subquery}"
        valid = {tuple(r) for r in (self._results(base + " LIMIT 1000", push_down=False) or [])}
        assert len(valid) == 16, f"expected 16 distinct matching rows (8 per session x 2), got {len(valid)}"
        for push in (True, False):
            rows = self._results(limited, push_down=push) or []
            assert len(rows) == 5, f"push={push}: LIMIT 5 must bind to exactly 5 rows, got {len(rows)}: {rows}"
            assert all(tuple(r) in valid for r in rows), f"push={push}: returned a row outside the matching set: {rows}"

    def test_exec_binding_limit_true_fan_out_returns_valid_rows_both_ways(self):
        # The highest-risk shape: a BINDING inner LIMIT (below the matching-event count) AND a true one-to-many
        # fan-out (self-join on distinct_id, all events share one distinct_id, so each a-event joins to every
        # b-event). The pushed inner LIMIT cuts EVENTS before the join, so the joined output still has >= LIMIT
        # rows; both forms must return exactly LIMIT rows from the full valid set. 6 events on one distinct_id
        # -> 36 joined pairs, LIMIT 3 binds.
        self._create_session("2024-01-02T00:00:00", "u1", "pro", *[f"2024-01-02T10:0{m}:00" for m in range(6)])
        self._create_session("2023-06-01T00:00:00", "u_old", "pro", "2023-06-01T09:00:00")  # out of range, dropped
        flush_persons_and_events()
        base = (
            "SELECT a.timestamp AS at, b.timestamp AS bt FROM events AS a "
            "LEFT JOIN events AS b ON a.distinct_id = b.distinct_id "
            "WHERE a.timestamp >= '2024-01-01' AND a.timestamp < '2024-01-08'"
        )
        limited = base + " LIMIT 3"
        printed = self._print_pushdown_sql(limited)
        assert ") AS a LEFT JOIN" in printed, f"expected the fan-out self-join left scan to push:\n{printed}"
        subquery = printed.split("FROM (", 1)[1].split(") AS a LEFT JOIN", 1)[0]
        assert "LIMIT 3" in subquery, f"expected the pushed inner LIMIT to bind:\n{subquery}"
        valid = {tuple(r) for r in (self._results(base + " LIMIT 1000", push_down=False) or [])}
        assert len(valid) == 36, f"expected 36 joined pairs (6 events x 6 self-join matches), got {len(valid)}"
        for push in (True, False):
            rows = self._results(limited, push_down=push) or []
            assert len(rows) == 3, f"push={push}: LIMIT 3 must bind to exactly 3 rows, got {len(rows)}: {rows}"
            assert all(tuple(r) in valid for r in rows), f"push={push}: returned a row outside the matching set: {rows}"

    def _setup_cohort_data(self) -> "Cohort":
        # c_in ($os=Chrome) is in the cohort with 2 in-range events; c_out ($os=Firefox) is out, with 1.
        _create_person(team=self.team, distinct_ids=["c_in"], properties={"$os": "Chrome"}, is_identified=True)
        _create_person(team=self.team, distinct_ids=["c_out"], properties={"$os": "Firefox"}, is_identified=True)
        self._create_session("2024-01-02T00:00:00", "c_in", "pro", "2024-01-02T10:00:00", "2024-01-02T10:05:00")
        self._create_session("2024-01-03T00:00:00", "c_out", "pro", "2024-01-03T09:00:00")
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team, groups=[{"properties": [{"key": "$os", "value": "Chrome", "type": "person"}]}]
        )
        recalculate_cohortpeople(cohort, pending_version=0, initiating_user_id=None)
        return cohort

    # Cohort predicates must never push, regardless of how IN COHORT resolves: inCohortVia=LEFTJOIN leaves an
    # unresolved InCohort op (kept outer), and SUBQUERY / CONJOINED / inline resolve to a nested subquery
    # (kept outer), across every personsOnEventsMode, so the `person_id` resolution (direct vs lazy override)
    # can't make it slip through. Each shape must decline (run flat) and stay result-equivalent on vs off.
    _COHORT_SHAPES = [
        (
            "subquery_person_id_direct",
            InCohortVia.SUBQUERY,
            PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            InlineCohortCalculation.OFF,
            "IN COHORT",
            2,
        ),
        (
            "subquery_override_on_events",
            InCohortVia.SUBQUERY,
            PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
            InlineCohortCalculation.OFF,
            "IN COHORT",
            2,
        ),
        (
            "subquery_poe_disabled",
            InCohortVia.SUBQUERY,
            PersonsOnEventsMode.DISABLED,
            InlineCohortCalculation.OFF,
            "IN COHORT",
            2,
        ),
        (
            "leftjoin_person_id_direct",
            InCohortVia.LEFTJOIN,
            PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            InlineCohortCalculation.OFF,
            "IN COHORT",
            2,
        ),
        (
            "conjoined_person_id_direct",
            InCohortVia.LEFTJOIN_CONJOINED,
            PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            InlineCohortCalculation.OFF,
            "IN COHORT",
            2,
        ),
        (
            "subquery_inline_calc",
            InCohortVia.SUBQUERY,
            PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            InlineCohortCalculation.ALWAYS,
            "IN COHORT",
            2,
        ),
        (
            "not_in_cohort",
            InCohortVia.SUBQUERY,
            PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            InlineCohortCalculation.OFF,
            "NOT IN COHORT",
            1,
        ),
    ]

    @parameterized.expand(_COHORT_SHAPES)
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_exec_cohort_predicate_declines_and_stays_equivalent(
        self, _name, in_cohort_via, poe_mode, inline, predicate, expected_count
    ):
        cohort = self._setup_cohort_data()
        select = (
            f"SELECT event, session.$session_duration FROM events "
            f"WHERE timestamp >= '2024-01-01' AND timestamp < '2024-01-08' "
            f"AND person_id {predicate} {cohort.pk} LIMIT 50"
        )

        def mods(push: bool) -> HogQLQueryModifiers:
            return HogQLQueryModifiers(
                pushDownPredicates=push,
                inCohortVia=in_cohort_via,
                personsOnEventsMode=poe_mode,
                inlineCohortCalculation=inline,
            )

        printed, _ = prepare_and_print_ast(
            parse_select(select),
            HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=mods(True)),
            "clickhouse",
        )
        assert ") AS events LEFT JOIN" not in printed, f"{_name}: cohort predicate must not push:\n{printed}"
        on = execute_hogql_query(select, team=self.team, modifiers=mods(True)).results
        off = execute_hogql_query(select, team=self.team, modifiers=mods(False)).results
        assert sorted(on or []) == sorted(off or []), f"{_name}: pushdown changed results: on={on} off={off}"
        assert len(on or []) == expected_count, f"{_name}: expected {expected_count} rows, got {on}"

    # `events.person.properties.email` is a DIRECT events column (read from `person_properties`) under the
    # "properties on events" POE modes (so it's pushable) but a lazy persons join under "properties joined" /
    # disabled, where it declines. The pushdown runs before the person-property PropertySwapper, so the pushed
    # PropertyType is rewritten inside the subquery; the collector pre-exposes `person_properties`. Either way
    # results must stay equivalent on vs off.
    _POE_PERSON_PROPERTY_SHAPES = [
        ("properties_on_events_no_override", PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS, True),
        ("properties_on_events_override", PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS, True),
        ("properties_joined", PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED, False),
        ("poe_disabled", PersonsOnEventsMode.DISABLED, False),
    ]

    @parameterized.expand(_POE_PERSON_PROPERTY_SHAPES)
    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_exec_poe_person_property_filter(self, _name, poe_mode, expect_push):
        _create_person(team=self.team, distinct_ids=["pp_in"], properties={"email": "a@x.com"}, is_identified=True)
        _create_person(team=self.team, distinct_ids=["pp_out"], properties={"email": "b@x.com"}, is_identified=True)
        self._create_session("2024-01-02T00:00:00", "pp_in", "pro", "2024-01-02T10:00:00", "2024-01-02T10:05:00")
        self._create_session("2024-01-03T00:00:00", "pp_out", "pro", "2024-01-03T09:00:00")
        flush_persons_and_events()
        select = (
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND timestamp < '2024-01-08' AND person.properties.email = 'a@x.com' LIMIT 50"
        )

        def mods(push: bool) -> HogQLQueryModifiers:
            return HogQLQueryModifiers(pushDownPredicates=push, personsOnEventsMode=poe_mode)

        printed, _ = prepare_and_print_ast(
            parse_select(select),
            HogQLContext(team_id=self.team.pk, enable_select_queries=True, modifiers=mods(True)),
            "clickhouse",
        )
        pushed = ") AS events LEFT JOIN" in printed
        assert pushed is expect_push, f"{_name}: expected pushed={expect_push}:\n{printed}"
        if pushed:
            subquery = printed.split("FROM (", 1)[1].split(") AS events LEFT JOIN", 1)[0]
            assert "person_properties" in subquery, f"{_name}: subquery should read person_properties:\n{subquery}"
            assert "LIMIT" in subquery, f"{_name}: pushed subquery should carry an inner LIMIT:\n{subquery}"
        on = execute_hogql_query(select, team=self.team, modifiers=mods(True)).results
        off = execute_hogql_query(select, team=self.team, modifiers=mods(False)).results
        assert sorted(on or []) == sorted(off or []), f"{_name}: pushdown changed results: on={on} off={off}"
        assert len(on or []) == 2, f"{_name}: expected 2 rows (pp_in's events), got {on}"

    def test_exec_array_join_predicate_not_pushed_stays_equivalent(self):
        # arrayJoin in a predicate is residual (it can't be pushed into the events subquery), so the whole
        # pushdown declines: with a residual predicate left on the outer query an inner LIMIT would be unsafe,
        # so the query runs flat. Results must stay equivalent regardless.
        self._create_data()
        select = (
            f"SELECT arrayJoin([1, 2]) AS n, session.$session_duration AS d FROM events "
            f"WHERE {self._RANGE} AND arrayJoin([1, 2]) > 0"
        )
        printed = self._print_pushdown_sql(select)
        assert ") AS events LEFT JOIN" not in printed and ") AS e LEFT JOIN" not in printed, (
            f"expected pushdown to decline with a residual arrayJoin predicate:\n{printed}"
        )
        # 3 in-range events x arrayJoin([1, 2]) = 6 rows, identical on vs off.
        self._assert_pushdown_equivalent(select, expected_rows=6)

    def test_exec_array_join_via_aliased_events_column_not_pushed(self):
        # The arrayJoin is hidden behind a SELECT alias that shadows the `event` column and is referenced in
        # the WHERE. The bare-alias predicate is residual (an arrayJoin can't be pushed), so the whole
        # pushdown declines and the query runs flat. Results stay equivalent on vs off.
        self._create_data()
        select = (
            f"SELECT arrayJoin([event, 'extra']) AS event, session.$session_duration AS d FROM events "
            f"WHERE {self._RANGE} AND event = 'watched movie'"
        )
        printed = self._print_pushdown_sql(select)
        assert ") AS events LEFT JOIN" not in printed and ") AS e LEFT JOIN" not in printed, (
            f"expected pushdown to decline with a residual arrayJoin alias predicate:\n{printed}"
        )
        self._assert_pushdown_equivalent(select, expected_rows=3)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_exec_timestamp_filter_with_session_join(self):
        self._create_data()
        select = (
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND timestamp < '2024-01-08' LIMIT 50"
        )
        printed = self._print_pushdown_sql(select)
        assert printed == self._events_schema_snapshot()
        assert "LIMIT" in self._events_subquery(printed)
        self._assert_pushdown_equivalent(select, expected_rows=3)

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_exec_aliased_events_timestamp_filter_with_session_join(self):
        self._create_data()
        select = (
            "SELECT e.event, session.$session_duration FROM events AS e "
            "WHERE e.timestamp >= '2024-01-01' AND e.timestamp < '2024-01-08' LIMIT 50"
        )
        printed = self._print_pushdown_sql(select)
        assert printed == self._events_schema_snapshot()
        assert ") AS e LEFT JOIN" in printed, f"expected pushdown to wrap events:\n{printed}"
        subquery = printed.split("FROM (", 1)[1].split(") AS e LEFT JOIN", 1)[0]
        assert "LIMIT" in subquery
        self._assert_pushdown_equivalent(select, expected_rows=3)

    def test_exec_property_filter_pushes_with_inner_limit(self):
        # A non-materialized property filter forces a raw `properties` blob read in the subquery, which
        # regresses without a short-circuit. With no ORDER BY / residual predicate and a LEFT join, the
        # transform pushes a LIMIT into the subquery so the blob read stops early; results stay identical.
        self._create_data()
        select = (
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND timestamp < '2024-01-08' AND properties.tier = 'pro' LIMIT 50"
        )
        subquery = self._events_subquery(self._print_pushdown_sql(select))
        assert "LIMIT 50" in subquery, f"expected the pushed LIMIT in the events subquery:\n{subquery}"
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert "events.properties.tier" in subquery, f"expected JSON subcolumn filter in the subquery:\n{subquery}"
            assert "JSONExtract" not in subquery, f"new events schema should not use JSONExtract here:\n{subquery}"
        else:
            assert "JSONExtract" in subquery, f"expected the raw-blob filter in the subquery:\n{subquery}"
        on = self._assert_results_equivalent(select)
        assert len(on) == 2

    def test_exec_aliased_property_filter_pushes_with_inner_limit(self):
        # Same blob-safe-push path with an aliased events table: the inner subquery keeps the `e` alias and
        # carries the pushed LIMIT.
        self._create_data()
        select = (
            "SELECT e.event, session.$session_duration FROM events AS e "
            "WHERE e.timestamp >= '2024-01-01' AND e.timestamp < '2024-01-08' AND e.properties.tier = 'pro' LIMIT 50"
        )
        printed = self._print_pushdown_sql(select)
        assert ") AS e LEFT JOIN" in printed, f"expected property filter pushed into an events subquery:\n{printed}"
        subquery = printed.split("FROM (", 1)[1].split(") AS e LEFT JOIN", 1)[0]
        assert f"FROM {self._events_table_ref()} AS e" in subquery, (
            f"expected the subquery to define alias `e`:\n{subquery}"
        )
        assert "LIMIT 50" in subquery, f"expected the pushed LIMIT in the subquery:\n{subquery}"
        on = self._assert_results_equivalent(select)
        assert len(on) == 2

    def test_exec_blob_property_with_order_by_declines(self):
        # The same raw-blob property filter WITH an ORDER BY can't push a LIMIT safely (the sort needs the
        # whole set), so the transform declines rather than read the blob across a wide scan. Still equivalent.
        self._create_data()
        select = (
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND timestamp < '2024-01-08' AND properties.tier = 'pro' ORDER BY timestamp"
        )
        printed = self._print_pushdown_sql(select)
        assert ") AS events LEFT JOIN" not in printed, (
            f"expected pushdown to decline (raw blob, no safe limit to short-circuit):\n{printed}"
        )
        self._assert_pushdown_equivalent(select, expected_rows=2)

    def test_exec_alias_shadowing_constant_predicate_stays_correct(self):
        # A SELECT alias whose name collides with an events column but whose expression is a constant
        # must not be pushed by name: `WHERE event = 'x'` means `'x' = 'x'` (true), not events.event = 'x'.
        self._create_data()
        select = (
            "SELECT 'x' AS event, session.$session_duration FROM events "
            "WHERE event = 'x' AND timestamp >= '2024-01-01' AND timestamp < '2024-01-08' LIMIT 50"
        )
        self._assert_pushdown_equivalent(select, expected_rows=3)

    def test_exec_alias_shadowing_joined_predicate_stays_correct(self):
        # A SELECT alias whose name collides with an events column but whose expression references the
        # joined session table must not be pushed into the events subquery. The residual joined predicate
        # makes the whole pushdown decline; results stay equivalent either way.
        self._create_data()
        select = (
            "SELECT ifNull(session.$session_duration, 0) AS event FROM events "
            "WHERE event >= 0 AND timestamp >= '2024-01-01' AND timestamp < '2024-01-08' LIMIT 50"
        )
        self._assert_pushdown_equivalent(select, expected_rows=3)

    def test_exec_events_prewhere_with_session_join_stays_correct(self):
        # A pushable events-column PREWHERE plus a session join must stay result-equivalent on/off, and the
        # PREWHERE must stay a PREWHERE on the inner events scan (not be demoted to WHERE). With no ORDER BY
        # and a LEFT join the pushdown also carries an inner LIMIT.
        self._create_data()
        select = (
            "SELECT event, session.$session_duration FROM events "
            "PREWHERE timestamp >= '2024-01-01' AND timestamp < '2024-01-08' "
            "WHERE event = 'watched movie' LIMIT 50"
        )
        printed = self._print_pushdown_sql(select)
        subquery = "".join(printed.split()).split("FROM(", 1)[1].split(")ASeventsLEFTJOIN", 1)[0]
        assert "PREWHERE" in subquery, "pushed PREWHERE should stay a PREWHERE on the inner scan:\n" + printed
        assert "LIMIT" in subquery, "pushed subquery should carry an inner LIMIT:\n" + printed
        self._assert_pushdown_equivalent(select, expected_rows=3)

    def test_exec_prewhere_only_with_session_join_stays_correct(self):
        # A PREWHERE-only events query (no WHERE) still pushes: the subquery keeps the PREWHERE and the
        # printer injects the team_id guard as the subquery's WHERE. Exercises the where=None subquery path.
        self._create_data()
        select = (
            "SELECT event, session.$session_duration FROM events "
            "PREWHERE timestamp >= '2024-01-01' AND timestamp < '2024-01-08' LIMIT 50"
        )
        printed = self._print_pushdown_sql(select)
        subquery = "".join(printed.split()).split("FROM(", 1)[1].split(")ASeventsLEFTJOIN", 1)[0]
        assert "PREWHERE" in subquery, "pushed PREWHERE should stay a PREWHERE on the inner scan:\n" + printed
        assert "LIMIT" in subquery, "pushed subquery should carry an inner LIMIT:\n" + printed
        self._assert_pushdown_equivalent(select, expected_rows=3)

    def test_exec_non_pushable_prewhere_bails(self):
        # A PREWHERE referencing a non-events (joined) column can't be pushed and can't stay on the outer
        # query either: after pushdown the outer FROM is a subquery, where PREWHERE is invalid. Pushdown
        # must bail so we never emit a PREWHERE on a subquery. (The query is already invalid CH regardless,
        # so this is a print-level check that we don't make it worse, not an execution one.)
        self._create_data()
        select = (
            "SELECT event, session.$session_duration FROM events "
            "PREWHERE session.$session_duration > 0 AND timestamp >= '2024-01-01' "
            "WHERE event = 'watched movie'"
        )
        printed = self._print_pushdown_sql(select)
        assert ") AS events LEFT JOIN" not in printed, (
            f"pushdown must bail when a PREWHERE predicate isn't fully pushable (no PREWHERE on a subquery):\n{printed}"
        )

    def test_exec_aliased_function_shadowing_column_pushes_full_expression(self):
        # A non-identity function aliased back to its own column name (upper(event) AS event) and filtered
        # on must push the full expression, not re-bind the bare name to the raw column (which would drop
        # upper() and filter case-sensitively). Events are lowercase, so re-binding would return 0 rows.
        self._create_data()
        select = (
            "SELECT upper(event) AS event, session.$session_duration FROM events "
            "WHERE event = 'WATCHED MOVIE' AND timestamp >= '2024-01-01' AND timestamp < '2024-01-08' "
            "LIMIT 50"
        )
        self._assert_pushdown_equivalent(select, expected_rows=3)

    def test_exec_events_only_or_predicate_stays_correct(self):
        # An OR predicate referencing only events columns is pushed atomically and must stay equivalent.
        self._create_data()
        select = (
            "SELECT event, session.$session_duration FROM events "
            "WHERE (event = 'watched movie' OR event = 'nonexistent') "
            "AND timestamp >= '2024-01-01' AND timestamp < '2024-01-08' LIMIT 50"
        )
        self._assert_pushdown_equivalent(select, expected_rows=3)

    def _create_diverse_data(self) -> None:
        # A second event name (so event filters actually discriminate) and a row whose `$session_id` is
        # invalid (so its LEFT JOIN finds no session and the duration is NULL, an unmatched-join row).
        s1, s2 = str(uuid7("2024-01-02T00:00:00")), str(uuid7("2024-01-03T00:00:00"))
        rows = [
            ("u1", "watched movie", s1, "2024-01-02T10:00:00"),
            ("u1", "watched movie", s1, "2024-01-02T10:05:00"),
            ("u2", "added to cart", s2, "2024-01-03T09:00:00"),
            ("u3", "watched movie", "", "2024-01-04T09:00:00"),  # invalid session_id → unmatched LEFT JOIN
        ]
        for distinct_id, event, session_id, ts in rows:
            _create_event(
                team=self.team,
                event=event,
                distinct_id=distinct_id,
                timestamp=ts,
                properties={"$session_id": session_id, "tier": "pro"},
            )
        flush_persons_and_events()

    def test_exec_event_filter_discriminates_and_stays_equivalent(self):
        # With two event names, an event-name filter must return fewer rows than the unfiltered baseline
        # (otherwise the shape doesn't actually test the predicate), and stay pushdown-equivalent.
        self._create_diverse_data()
        baseline = f"SELECT event, session.$session_duration FROM events WHERE {self._RANGE} LIMIT 50"
        filtered = f"SELECT event, session.$session_duration FROM events WHERE {self._RANGE} AND event = 'watched movie' LIMIT 50"
        self._assert_pushdown_equivalent(baseline, expected_rows=4)
        self._assert_pushdown_equivalent(filtered, expected_rows=3)

    def test_exec_unmatched_left_join_null_duration_stays_equivalent(self):
        # The row with an invalid `$session_id` has a NULL session duration (LEFT JOIN miss). Pushdown must
        # not change which rows survive or their NULL durations.
        self._create_diverse_data()
        select = f"SELECT event, session.$session_duration AS d FROM events WHERE {self._RANGE} LIMIT 50"
        self._assert_pushdown_equivalent(select, expected_rows=4)
        # the unmatched row must actually be present with a NULL/zero duration in both modes
        results = self._results(select, push_down=True)
        assert any(row[1] in (None, 0) for row in results), f"expected an unmatched-join NULL/0 duration row: {results}"

    _RANGE = "timestamp >= '2024-01-01' AND timestamp < '2024-01-08'"
    # The core "pure optimization" invariant across many query shapes. Each shape pushes: a session (LEFT)
    # join, a fully-pushable events predicate, no ORDER BY / aggregate, and an effective LIMIT. The runner
    # asserts the events subquery (with its inner LIMIT) was created, then compares sorted results on vs off
    # (the inner LIMIT means there is no ORDER BY to pin row order).
    EQUIVALENCE_SHAPES = [
        ("baseline", f"SELECT event, session.$session_duration FROM events WHERE {_RANGE} LIMIT 50"),
        (
            "event_equals",
            f"SELECT event, session.$session_duration FROM events WHERE {_RANGE} AND event = 'watched movie' LIMIT 50",
        ),
        (
            "event_or",
            f"SELECT event, session.$session_duration FROM events WHERE {_RANGE} AND (event = 'watched movie' OR event = 'other') LIMIT 50",
        ),
        (
            "event_not",
            f"SELECT event, session.$session_duration FROM events WHERE {_RANGE} AND NOT (event = 'nope') LIMIT 50",
        ),
        (
            "event_in",
            f"SELECT event, session.$session_duration FROM events WHERE {_RANGE} AND event IN ('watched movie', 'other') LIMIT 50",
        ),
        (
            "comparison_ops",
            f"SELECT event, session.$session_duration FROM events WHERE timestamp > '2024-01-01' AND timestamp <= '2024-01-08' LIMIT 50",
        ),
        (
            "limit",
            f"SELECT event, session.$session_duration FROM events WHERE {_RANGE} LIMIT 50",
        ),
        (
            "aliased_table",
            f"SELECT e.event, session.$session_duration FROM events AS e WHERE e.timestamp >= '2024-01-01' AND e.timestamp < '2024-01-08' AND e.event = 'watched movie' LIMIT 50",
        ),
        (
            "aliased_function_shadowing",
            f"SELECT upper(event) AS event, session.$session_duration FROM events WHERE {_RANGE} AND event = 'WATCHED MOVIE' LIMIT 50",
        ),
        (
            # An aggregate inside a scalar subquery belongs to that subquery's scope; this outer query is
            # non-aggregate and must still push (the gate must not be fooled into declining).
            "scalar_subquery_aggregate",
            f"SELECT event, (SELECT count() FROM events) AS total, session.$session_duration FROM events WHERE {_RANGE} LIMIT 50",
        ),
    ]

    @parameterized.expand(EQUIVALENCE_SHAPES)
    def test_exec_pushdown_result_equivalence(self, _name: str, select: str):
        self._create_data()
        printed = self._print_pushdown_sql(select)
        assert ") AS events LEFT JOIN" in printed or ") AS e LEFT JOIN" in printed, (
            f"{_name}: expected pushdown to wrap events in a subquery, but it bailed:\n{printed}"
        )
        with_pushdown = self._results(select, push_down=True)
        without_pushdown = self._results(select, push_down=False)
        assert self._sorted(with_pushdown) == self._sorted(without_pushdown), (
            f"{_name}: pushdown changed results: on={with_pushdown} off={without_pushdown}"
        )

    # Shapes the gate must decline: a full-read (GROUP BY / DISTINCT / window) or an aggregate makes the
    # LIMIT unable to short-circuit the events scan; an ORDER BY blocks the inner LIMIT; and a residual
    # joined-table predicate (or ordering by a joined column) leaves a predicate on the outer query so the
    # inner LIMIT would be unsafe. In every case the query runs flat and results must be unchanged. ORDER BY
    # is kept here so the on/off comparison can stay order-sensitive (no inner LIMIT reshuffles the set).
    DECLINE_SHAPES = [
        (
            "group_by_aggregation",
            f"SELECT event, count() AS c, max(session.$session_duration) AS d FROM events WHERE {_RANGE} GROUP BY event ORDER BY event",
        ),
        (
            "group_by_having",
            f"SELECT event, count() AS c, max(session.$session_duration) AS d FROM events WHERE {_RANGE} GROUP BY event HAVING count() > 0 ORDER BY event",
        ),
        (
            "distinct",
            f"SELECT DISTINCT properties.tier AS t, session.$session_duration AS d FROM events WHERE {_RANGE} ORDER BY t, d",
        ),
        (
            "window_function",
            f"SELECT event, row_number() OVER (ORDER BY timestamp) AS rn, session.$session_duration AS d FROM events WHERE {_RANGE} ORDER BY timestamp, event",
        ),
        (
            # ORDER BY a joined column declines (any ORDER BY blocks the inner LIMIT, so the pushdown bails).
            "order_by_joined_column",
            f"SELECT event, session.$session_duration AS d FROM events WHERE {_RANGE} ORDER BY d, timestamp",
        ),
        (
            # A residual joined-table predicate (session.$session_duration) can't be pushed into the events
            # subquery, so the whole pushdown declines.
            "mixed_events_and_joined_predicate",
            f"SELECT event, session.$session_duration FROM events WHERE {_RANGE} AND session.$session_duration >= 0 ORDER BY timestamp",
        ),
        (
            # A clause-level ARRAY JOIN multiplies rows before the LIMIT applies, so pushing the LIMIT into the
            # events subquery (which runs before the ARRAY JOIN) would change the row count. Must decline.
            "array_join_clause",
            f"SELECT n, session.$session_duration AS d FROM events ARRAY JOIN [1, 2] AS n WHERE {_RANGE}",
        ),
        (
            # A total aggregation (no GROUP BY) consumes the whole filtered set before the LIMIT. Must decline.
            "aggregate_no_group_by",
            f"SELECT count() AS c, max(session.$session_duration) AS d FROM events WHERE {_RANGE}",
        ),
    ]

    @parameterized.expand(DECLINE_SHAPES)
    def test_exec_full_read_shapes_decline_but_stay_equivalent(self, _name: str, select: str):
        self._create_data()
        printed = self._print_pushdown_sql(select)
        assert ") AS events LEFT JOIN" not in printed and ") AS e LEFT JOIN" not in printed, (
            f"{_name}: expected pushdown to decline (no short-circuit possible), but it wrapped events:\n{printed}"
        )
        with_pushdown = self._results(select, push_down=True)
        without_pushdown = self._results(select, push_down=False)
        assert self._sorted(with_pushdown) == self._sorted(without_pushdown), (
            f"{_name}: pushdown changed results: on={with_pushdown} off={without_pushdown}"
        )


class TestEventsPredicatePushdownMaterializedExecution(_PushdownExecutionTestBase):
    """Pushdown must stay a pure optimization on teams that have materialized columns.

    The test ClickHouse has no materialized columns by default, so the rest of the suite never prints
    `events.mat_*`. These tests materialize a property first, so the printer reads the physical column and
    the pushdown subquery must expose it; without that exposure a property referenced outside the pushed
    predicate (SELECT / GROUP BY / ORDER BY / HAVING) prints `events.mat_tier` against a subquery alias that
    doesn't have it → `Unknown identifier`. Every assertion checks pushdown-on == pushdown-off.
    """

    def _create_data(self) -> None:
        # Same shape as the non-materialized suite; called inside a materialized() block so the physical
        # column is computed at insert time (ClickHouse MATERIALIZED columns are evaluated on INSERT).
        for distinct_id, tier, timestamps in [
            ("u1", "pro", ["2024-01-02T10:00:00", "2024-01-02T10:05:00"]),
            ("u2", "free", ["2024-01-05T09:00:00"]),
            ("u3", "pro", ["2023-06-01T09:00:00"]),
        ]:
            session_id = str(uuid7(timestamps[0]))
            for ts in timestamps:
                _create_event(
                    team=self.team,
                    event="watched movie",
                    distinct_id=distinct_id,
                    timestamp=ts,
                    properties={"$session_id": session_id, "tier": tier},
                )
        flush_persons_and_events()

    def _assert_equivalent(self, select: str, *, expected_rows: int) -> None:
        with_pushdown = self._assert_results_equivalent(select)
        assert len(with_pushdown) == expected_rows, f"expected {expected_rows} rows, got {with_pushdown}"

    _RANGE = "timestamp >= '2024-01-01' AND timestamp < '2024-01-08'"

    def test_exec_materialized_property_in_outer_select(self):
        # The CRITICAL repro: a materialized property in the outer SELECT. The subquery must expose
        # `mat_tier` or the outer `events.mat_tier` is an Unknown identifier.
        with materialized("events", "tier") as mat_col:
            self._create_data()
            select = (
                f"SELECT properties.tier AS t, session.$session_duration AS d FROM events WHERE {self._RANGE} LIMIT 50"
            )
            printed = self._print_pushdown_sql(select)
            subquery = self._events_subquery(printed)
            self._assert_events_property_source(subquery, "tier", mat_col.name)
            assert "LIMIT" in subquery, f"expected the pushed subquery to carry an inner LIMIT:\n{printed}"
            # The materialized property must NOT also drag the raw `properties` blob into the subquery
            # projection (over-projection would force a ~100x-slower full-Map read). Guards drift on the
            # plain-materialized PropertyType path, mirroring the JSONHas blob-projection guard.
            assert "properties AS properties" not in subquery, (
                f"materialized property over-projected the blob:\n{printed}"
            )
            self._assert_equivalent(select, expected_rows=3)

    def test_exec_materialized_property_as_join_key_exposes_mat_column(self):
        # A materialized property used as the events-side join key. The key expression stays in the ON (a subquery
        # column would read as nullable and break join-key detection), so the physical pass rewrites the ON's
        # property to `events.mat_tier`, which the subquery must expose — without it the ON references `mat_tier`
        # against a subquery alias that lacks it (Unknown identifier). This asserts the exposure on the printed SQL;
        # end-to-end execution of a property join key is covered by test_query.test_join_with_property_materialized.
        with materialized("events", "tier") as mat_col:
            self._create_data()
            select = (
                "SELECT events.event AS ae, p.id FROM events "
                "LEFT JOIN persons p ON p.properties.tier = events.properties.tier "
                "WHERE events.timestamp >= '2024-01-01' AND events.timestamp < '2024-01-08' LIMIT 50"
            )
            subquery = self._events_subquery(self._print_pushdown_sql(select))
            self._assert_events_property_source(subquery, "tier", mat_col.name)

    def test_exec_materialized_property_in_order_by_declines(self):
        # A materialized property in ORDER BY: any ORDER BY blocks the inner LIMIT, so the pushdown declines
        # and the query runs flat. Results must stay equivalent.
        with materialized("events", "tier"):
            self._create_data()
            select = f"SELECT event, session.$session_duration FROM events WHERE {self._RANGE} ORDER BY properties.tier, timestamp"
            printed = self._print_pushdown_sql(select)
            assert ") AS events LEFT JOIN" not in printed and ") AS e LEFT JOIN" not in printed, (
                f"expected pushdown to decline with an ORDER BY:\n{printed}"
            )
            self._assert_equivalent(select, expected_rows=3)

    def test_exec_materialized_property_filter_pushed_uses_mat_column(self):
        # Property in the pushed predicate: the subquery WHERE must use the materialized column, not the
        # JSONExtract blob path, and results must match pushdown-off.
        with materialized("events", "tier") as mat_col:
            self._create_data()
            select = f"SELECT event, session.$session_duration FROM events WHERE {self._RANGE} AND properties.tier = 'pro' LIMIT 50"
            printed = self._print_pushdown_sql(select)
            subquery = self._events_subquery(printed)
            self._assert_events_property_source(subquery, "tier", mat_col.name)
            assert "JSONExtract" not in subquery, (
                f"materialized column should avoid the JSONExtract blob path:\n{printed}"
            )
            assert "LIMIT" in subquery, f"expected the pushed subquery to carry an inner LIMIT:\n{printed}"
            self._assert_equivalent(select, expected_rows=2)

    def test_exec_aliased_materialized_property_filter_pushed_uses_inner_table(self):
        # When the events table is aliased (FROM events AS e) and a *materialized* property is in the pushed
        # predicate, the printer renders `e.mat_tier` from the property's type. The inner subquery keeps the
        # `e` alias on its own events scan, so `e.mat_tier` resolves there instead of being an unknown
        # identifier (a rewrite-to-inner-table approach would miss the materialized property path).
        with materialized("events", "tier") as mat_col:
            self._create_data()
            select = (
                "SELECT e.event, session.$session_duration FROM events AS e "
                "WHERE e.timestamp >= '2024-01-01' AND e.timestamp < '2024-01-08' AND e.properties.tier = 'pro' "
                "LIMIT 50"
            )
            printed = self._print_pushdown_sql(select)
            assert ") AS e LEFT JOIN" in printed, (
                f"expected the materialized property filter pushed into a subquery:\n{printed}"
            )
            subquery = printed.split("FROM (", 1)[1].split(") AS e LEFT JOIN", 1)[0]
            if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
                assert mat_col.name not in subquery, f"new events schema should not use {mat_col.name}:\n{subquery}"
                assert "e.properties.tier" in subquery, f"expected JSON subcolumn in the pushed predicate:\n{subquery}"
            else:
                assert mat_col.name in subquery, f"expected the materialized column in the pushed predicate:\n{printed}"
            assert f"FROM {self._events_table_ref()} AS e" in subquery, (
                f"expected the subquery to define alias `e`:\n{subquery}"
            )
            assert "LIMIT" in subquery, f"expected the pushed subquery to carry an inner LIMIT:\n{printed}"
            self._assert_equivalent(select, expected_rows=2)

    def test_exec_materialized_property_not_referenced_outside_predicate(self):
        # Property only in the pushed predicate (not the outer query): still equivalent, and the subquery
        # reads the materialized column rather than the properties blob.
        with materialized("events", "tier") as mat_col:
            self._create_data()
            select = f"SELECT event, session.$session_duration FROM events WHERE {self._RANGE} AND properties.tier IN ('pro', 'free') LIMIT 50"
            printed = self._print_pushdown_sql(select)
            self._assert_events_property_source(self._events_subquery(printed), "tier", mat_col.name)
            self._assert_equivalent(select, expected_rows=3)

    MATERIALIZED_SHAPES = [
        (
            "property_equals",
            f"SELECT event, session.$session_duration FROM events WHERE {_RANGE} AND properties.tier = 'pro' LIMIT 50",
        ),
        (
            "property_in_select_and_filter",
            f"SELECT properties.tier AS t, session.$session_duration FROM events WHERE {_RANGE} AND properties.tier = 'pro' LIMIT 50",
        ),
    ]

    @parameterized.expand(MATERIALIZED_SHAPES)
    def test_exec_materialized_pushdown_result_equivalence(self, _name: str, select: str):
        with materialized("events", "tier") as mat_col:
            self._create_data()
            printed = self._print_pushdown_sql(select)
            self._assert_events_property_source(self._events_subquery(printed), "tier", mat_col.name)
            with_pushdown = self._results(select, push_down=True)
            without_pushdown = self._results(select, push_down=False)
            assert self._sorted(with_pushdown) == self._sorted(without_pushdown), (
                f"{_name}: pushdown changed results: on={with_pushdown} off={without_pushdown}"
            )


class TestEventsPredicatePushdownPropertyGroupsExecution(_PushdownExecutionTestBase):
    """Pushdown must stay a pure optimization under propertyGroupsMode=OPTIMIZED (the PostHog Cloud default).

    In OPTIMIZED mode the printer rewrites `JSONHas(properties, 'k')` into `has(events.properties_group_*,
    'k')`, referencing a property-group Map column. JSONHas's argument is the bare `properties` column (not
    a `properties.k` PropertyType), so the subquery must still expose that Map column or an outer-scope
    JSONHas resolves against a column the subquery alias doesn't carry → `Unknown identifier`.
    """

    _property_groups_mode = PropertyGroupsMode.OPTIMIZED

    def _create_data(self) -> None:
        # Two events that have the `tier` property and one that doesn't, so JSONHas(properties, 'tier')
        # discriminates (2 true, 1 false). All in range with a valid session for the lazy join.
        for distinct_id, props, timestamps in [
            ("u1", {"tier": "pro"}, ["2024-01-02T10:00:00", "2024-01-02T10:05:00"]),
            ("u2", {}, ["2024-01-05T09:00:00"]),
        ]:
            session_id = str(uuid7(timestamps[0]))
            for ts in timestamps:
                _create_event(
                    team=self.team,
                    event="watched movie",
                    distinct_id=distinct_id,
                    timestamp=ts,
                    properties={"$session_id": session_id, **props},
                )
        flush_persons_and_events()

    _RANGE = "timestamp >= '2024-01-01' AND timestamp < '2024-01-08'"

    def test_exec_outer_json_has_exposes_property_group_column(self):
        # The reproduced break: an outer JSONHas → printer emits has(events.properties_group_*), which the
        # subquery must expose. JSONHas is in the SELECT (referenced outside the pushed predicate) so the
        # pushdown still fires with an inner LIMIT.
        self._create_data()
        select = (
            f"SELECT event, JSONHas(properties, 'tier') AS h, session.$session_duration FROM events "
            f"WHERE {self._RANGE} LIMIT 50"
        )
        printed = self._print_pushdown_sql(select)
        self._assert_json_has_source(self._events_subquery(printed))
        with_pushdown = self._results(select, push_down=True)
        without_pushdown = self._results(select, push_down=False)
        assert self._sorted(with_pushdown) == self._sorted(without_pushdown), (
            f"pushdown changed results: on={with_pushdown} off={without_pushdown}"
        )
        assert len(with_pushdown or []) == 3

    def test_exec_json_has_does_not_project_properties_blob(self):
        # Under OPTIMIZED the printer reads only the property-group Map column for JSONHas, never the
        # `properties` blob. When JSONHas is the sole `properties` reference, the subquery must expose the
        # Map column and NOT project the full blob (which would force a ~100x Map read for nothing).
        self._create_data()
        select = (
            f"SELECT event, JSONHas(properties, 'tier') AS h, session.$session_duration FROM events "
            f"WHERE {self._RANGE} LIMIT 50"
        )
        subquery = self._events_subquery(self._print_pushdown_sql(select))
        self._assert_json_has_source(subquery)
        assert "properties AS properties" not in subquery, (
            f"the raw properties blob must NOT be projected when only JSONHas reads it:\n{subquery}"
        )

    def test_exec_json_has_in_select_stays_equivalent(self):
        self._create_data()
        select = (
            f"SELECT JSONHas(properties, 'tier') AS h, session.$session_duration FROM events "
            f"WHERE {self._RANGE} LIMIT 50"
        )
        printed = self._print_pushdown_sql(select)
        self._assert_json_has_source(self._events_subquery(printed))
        with_pushdown = self._results(select, push_down=True)
        without_pushdown = self._results(select, push_down=False)
        assert self._sorted(with_pushdown) == self._sorted(without_pushdown), (
            f"pushdown changed results: on={with_pushdown} off={without_pushdown}"
        )

    def test_exec_json_has_property_filter_pushed_stays_equivalent(self):
        # JSONHas in the pushed predicate (WHERE): goes into the subquery, which can reference the group
        # column directly. Must stay equivalent.
        self._create_data()
        select = (
            f"SELECT event, session.$session_duration FROM events "
            f"WHERE {self._RANGE} AND JSONHas(properties, 'tier') LIMIT 50"
        )
        with_pushdown = self._results(select, push_down=True)
        without_pushdown = self._results(select, push_down=False)
        assert self._sorted(with_pushdown) == self._sorted(without_pushdown), (
            f"pushdown changed results: on={with_pushdown} off={without_pushdown}"
        )
        assert len(with_pushdown or []) == 2  # only u1's two events have the tier property

    def test_exec_property_type_uses_property_group_column(self):
        # `properties.tier` (a lowered PropertyAccess value read, not JSONHas) under OPTIMIZED is read from the property-group
        # Map column by the printer; the collector's PropertyType path must expose it too. Distinct code
        # path from the JSONHas tests above (visit_field/_collect_materialized_column, not visit_call).
        self._create_data()
        select = f"SELECT properties.tier AS t, session.$session_duration AS d FROM events WHERE {self._RANGE} LIMIT 50"
        printed = self._print_pushdown_sql(select)
        subquery = self._events_subquery(printed)
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert "properties_group" not in subquery, f"new events schema should not use property groups:\n{subquery}"
            assert "events.properties.tier" in subquery, f"expected JSON subcolumn in subquery:\n{subquery}"
        else:
            assert "properties_group" in subquery, printed
        with_pushdown = self._results(select, push_down=True)
        without_pushdown = self._results(select, push_down=False)
        assert self._sorted(with_pushdown) == self._sorted(without_pushdown), (
            f"pushdown changed results: on={with_pushdown} off={without_pushdown}"
        )
        assert len(with_pushdown or []) == 3  # u1's two tier='pro' events and u2's no-tier event

    def test_exec_is_not_null_uses_property_group_column(self):
        # Under OPTIMIZED the printer rewrites isNull/isNotNull(properties.k) to the property-group has()
        # expression, so the Map column must be exposed. The arg is a PropertyType (visit_field path), so
        # the group column is exposed by _collect_materialized_column; pin that equivalence here.
        self._create_data()
        select = (
            f"SELECT isNotNull(properties.tier) AS has_tier, session.$session_duration AS d "
            f"FROM events WHERE {self._RANGE} LIMIT 50"
        )
        printed = self._print_pushdown_sql(select)
        subquery = self._events_subquery(printed)
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert "properties_group" not in subquery, f"new events schema should not use property groups:\n{subquery}"
            assert "events.properties.tier" in subquery, f"expected JSON subcolumn in subquery:\n{subquery}"
        else:
            assert "properties_group" in subquery, printed
        with_pushdown = self._results(select, push_down=True)
        without_pushdown = self._results(select, push_down=False)
        assert self._sorted(with_pushdown) == self._sorted(without_pushdown), (
            f"pushdown changed results: on={with_pushdown} off={without_pushdown}"
        )
        assert len(with_pushdown or []) == 3  # u1's two events (has tier) and u2's event (no tier)

    def test_exec_having_on_property_alias_stays_correct(self):
        # A non-aggregate HAVING drops rows after the join, so `_safe_inner_limit` declines the pushdown (a pushed
        # LIMIT could under-produce). The query compiles flat; the comparison on the alias must still resolve to the
        # property correctly and match the same rows with the modifier on and off. (If the decline is ever relaxed,
        # the tables-in-scope guard is the second barrier: it stops the alias comparison from being rewritten to a
        # bare events column the subquery doesn't project.)
        self._create_data()
        select = (
            f"SELECT properties.tier AS t, session.$session_duration AS d "
            f"FROM events WHERE {self._RANGE} HAVING t = 'pro' LIMIT 50"
        )
        with_pushdown = self._assert_results_equivalent(select)
        assert len(with_pushdown) == 2  # u1's two tier='pro' events


class TestEventsPredicatePushdownDmatExecution(_PushdownExecutionTestBase):
    """Pushdown must expose dmat (dynamic materialized) columns in the subquery too.

    A property with a READY MaterializedColumnSlot is read from `dmat_string_<n>` by the printer, so an
    outer reference to that property after pushdown must resolve against the subquery alias. The test DB
    has the physical dmat columns but `_create_event` doesn't populate them, so events are inserted with
    the column pre-filled (same approach as test_property_types_dmat.py).
    """

    _SLOT_INDEX = 0
    _pass_team = True  # the print context needs the team to resolve the dmat slot

    def _setup_dmat_events(self) -> None:
        prop_def = PropertyDefinition.objects.create(
            team=self.team,
            name="tier",
            property_type=PropertyType.String,
            type=PropertyDefinition.Type.EVENT,
        )
        MaterializedColumnSlot.objects.create(
            team=self.team,
            property_definition=prop_def,
            slot_index=self._SLOT_INDEX,
            state=MaterializedColumnSlotState.READY,
        )
        for distinct_id, tier in [("u1", "pro"), ("u2", "free")]:
            if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
                _create_event(
                    team=self.team,
                    event="watched movie",
                    distinct_id=distinct_id,
                    timestamp="2024-01-02T10:00:00",
                    properties={"tier": tier},
                )
                continue
            sync_execute(
                f"""
                INSERT INTO sharded_events (uuid, team_id, event, distinct_id, timestamp, properties, dmat_string_{self._SLOT_INDEX})
                SELECT %(uuid)s, %(team_id)s, 'watched movie', %(distinct_id)s, now(), %(properties)s, %(dmat)s
                """,
                {
                    "uuid": str(uuid4()),
                    "team_id": self.team.pk,
                    "distinct_id": distinct_id,
                    "properties": json.dumps({"tier": tier}),
                    "dmat": tier,
                },
                flush=False,
            )
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            flush_persons_and_events()

    def test_exec_dmat_property_in_select_stays_equivalent(self):
        self._setup_dmat_events()
        select = "SELECT properties.tier AS t, session.$session_duration AS d FROM events WHERE timestamp >= '2020-01-01' LIMIT 50"
        printed = self._print_pushdown_sql(select)
        subquery = self._events_subquery(printed)
        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            assert f"dmat_string_{self._SLOT_INDEX}" not in subquery, printed
            assert "events.properties.tier" in subquery, printed
        else:
            assert f"dmat_string_{self._SLOT_INDEX}" in subquery, printed
        on = self._assert_results_equivalent(select)
        assert len(on) == 2
