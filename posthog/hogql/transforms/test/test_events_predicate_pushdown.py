from typing import Any

import pytest
from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import HogQLQueryModifiers
from posthog.hogql.parser import parse_select
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.test.utils import pretty_print_in_tests
from posthog.hogql.transforms.events_predicate_pushdown import (
    EventsFieldCollector,
    EventsPredicatePushdownTransform,
    LazyTypeDetector,
)


class TestEventsPredicatePushdownTransform(BaseTest):
    snapshot: Any
    maxDiff = None

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
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_with_alias_and_session_join(self):
        """Preserves events table alias in the subquery wrapper."""
        printed = self._print_select(
            "SELECT e.event, session.$session_duration FROM events AS e WHERE e.timestamp >= '2024-01-01'"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_without_join_no_pushdown(self):
        """No pushdown when there are no lazy joins."""
        printed = self._print_select("SELECT event FROM events WHERE timestamp >= '2024-01-01'")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_events_without_where_no_pushdown(self):
        """No pushdown when there is no WHERE clause."""
        printed = self._print_select("SELECT event, session.$session_duration FROM events")
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_session_duration_filter_stays_in_outer_where(self):
        """Session duration filters cannot be pushed down and stay in outer WHERE."""
        printed = self._print_select(
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND session.$session_duration > 0"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_multiple_pushable_predicates(self):
        """Multiple events-table predicates can be pushed down together."""
        printed = self._print_select(
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND event = '$pageview'"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_subquery_with_pushdown(self):
        """Subquery pushdown"""
        printed = self._print_select(
            "SELECT event, avg($session_duration) FROM ("
            "SELECT event, session.$session_duration FROM events "
            "WHERE timestamp >= '2024-01-01' AND (event = '$pageview' OR event = '$pageleave')"
            ") GROUP BY event"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_simple_events_with_person_join(self):
        """Simple test: events with person.id should resolve without predicate pushdown issues."""
        printed = self._print_select(
            "SELECT event, person.id FROM events WHERE timestamp > '2024-01-01'",
            # modifiers=HogQLQueryModifiers(pushDownPredicates=False),
        )

        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_pushdown_applied_to_nested_subqueries(self):
        query = """
                SELECT event, avg(duration)
                FROM (SELECT event, session.$session_duration as duration
                      FROM events
                      WHERE timestamp > '2024-01-01')
                GROUP BY event \
                """

        printed = self._print_select(query)

        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_poe_properties_with_session_join(self):
        """VirtualTable field poe.properties is included in subquery as person_properties."""
        printed = self._print_select(
            "SELECT event, poe.properties FROM events WHERE timestamp >= '2024-01-01' AND session.$session_duration > 0"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_poe_id_with_session_join(self):
        """VirtualTable field poe.id is included in subquery as person_id."""
        printed = self._print_select(
            "SELECT poe.id, session.$session_duration FROM events WHERE timestamp >= '2024-01-01'"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_poe_created_at_with_session_join(self):
        """VirtualTable field poe.created_at is included in subquery as person_created_at."""
        printed = self._print_select(
            "SELECT event, poe.created_at FROM events WHERE timestamp >= '2024-01-01' AND session.$session_duration > 0"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_multiple_poe_fields_with_session_join(self):
        """Multiple VirtualTable fields are all included in the subquery."""
        printed = self._print_select(
            "SELECT event, poe.id, poe.properties, poe.created_at FROM events "
            "WHERE timestamp >= '2024-01-01' AND session.$session_duration > 0"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_explicit_join_sessions_pushes_timestamp_down(self):
        """Explicit JOIN sessions pushes events.timestamp predicate into the subquery."""
        printed = self._print_select(
            "SELECT sessions.session_id, uniq(uuid) as uniq_uuid "
            "FROM events JOIN sessions ON events.$session_id = sessions.session_id "
            "WHERE events.timestamp > '2021-01-01' "
            "GROUP BY sessions.session_id"
        )
        assert printed == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_bare_timestamp_with_select_alias_pushes_down(self):
        """Bare timestamp in WHERE that shadows a SELECT alias is still pushed down."""
        printed = self._print_select(
            "SELECT event, toTimeZone(timestamp, 'UTC') as timestamp, session.$session_duration "
            "FROM events "
            "WHERE timestamp >= '2024-01-01' AND timestamp <= today()"
        )
        assert printed == self.snapshot


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
        )

        return ast.SelectQuery(
            select=[ast.Field(chain=["event"])],
            select_from=select_from,
            where=where_clause,
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


class TestLazyTypeDetector(BaseTest):
    """Tests for LazyTypeDetector using real HogQL queries.

    LazyTypeDetector finds LazyJoinType/LazyTableType in the AST which indicates
    that lazy join resolution hasn't completed - predicate pushdown should be skipped.
    """

    def setUp(self):
        super().setUp()
        from posthog.hogql.database.database import Database

        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team_id=self.team.pk, database=self.database, enable_select_queries=True)

    def _resolve_query(self, query: str) -> ast.SelectQuery:
        """Parse and resolve types for a query (without lazy table resolution)."""
        from posthog.hogql.resolver import resolve_types

        parsed = parse_select(query)
        resolved = resolve_types(parsed, self.context, dialect="clickhouse")
        assert isinstance(resolved, ast.SelectQuery)
        return resolved

    def test_detects_lazy_join_from_session_field(self):
        """Query accessing session.$session_duration has LazyJoinType before lazy resolution."""
        # session is a LazyJoin on events - produces LazyJoinType after resolve_types
        node = self._resolve_query("SELECT session.$session_duration FROM events")

        detector = LazyTypeDetector()
        detector.visit(node)

        assert detector.found_lazy_type is True

    def test_detects_lazy_join_from_person_field(self):
        """Query accessing person.id has LazyJoinType before lazy resolution."""
        node = self._resolve_query("SELECT person.id FROM events")

        detector = LazyTypeDetector()
        detector.visit(node)

        assert detector.found_lazy_type is True

    def test_no_lazy_type_for_direct_events_columns(self):
        """Query with only direct events columns has no lazy types."""
        node = self._resolve_query("SELECT event, timestamp, distinct_id FROM events")

        detector = LazyTypeDetector()
        detector.visit(node)

        assert detector.found_lazy_type is False

    def test_no_lazy_type_after_lazy_table_resolution(self):
        """After resolve_lazy_tables, there should be no lazy types in the main query fields."""
        from posthog.hogql.transforms.lazy_tables import resolve_lazy_tables

        resolved = self._resolve_query(
            "SELECT event, session.$session_duration FROM events WHERE timestamp > '2024-01-01'"
        )
        resolve_lazy_tables(resolved, "clickhouse", [], self.context)

        # Check only the SELECT fields (not the joined subqueries which may have their own structure)
        detector = LazyTypeDetector()
        for field in resolved.select:
            detector.visit(field)

        assert detector.found_lazy_type is False


class TestEventsFieldCollector(BaseTest):
    """Tests for EventsFieldCollector using real HogQL queries.

    EventsFieldCollector walks the AST to collect database columns needed from events table
    and detects non-direct fields (PropertyType, LazyJoinType) that prevent safe pushdown.
    """

    def setUp(self):
        super().setUp()
        from posthog.hogql.database.database import Database

        self.database = Database.create_for(team=self.team)
        self.context = HogQLContext(team_id=self.team.pk, database=self.database, enable_select_queries=True)

    def _resolve_query(self, query: str) -> tuple[ast.SelectQuery, ast.TableType | ast.TableAliasType]:
        """Parse, resolve types, and return query with events table type."""
        from posthog.hogql.resolver import resolve_types

        parsed = parse_select(query)
        resolved = resolve_types(parsed, self.context, dialect="clickhouse")
        assert isinstance(resolved, ast.SelectQuery)
        assert resolved.select_from is not None
        events_table_type = resolved.select_from.type
        assert isinstance(events_table_type, (ast.TableType, ast.TableAliasType))
        return resolved, events_table_type

    def test_collects_direct_database_columns(self):
        """Direct events columns like event, timestamp are collected."""
        node, events_table_type = self._resolve_query("SELECT event, timestamp FROM events WHERE distinct_id = 'user1'")

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        assert "event" in collector.collected_fields
        assert "timestamp" in collector.collected_fields
        assert "distinct_id" in collector.collected_fields
        assert collector.has_non_direct_fields is False

    def test_property_access_triggers_non_direct_flag(self):
        """Accessing properties.$browser triggers has_non_direct_fields."""
        node, events_table_type = self._resolve_query("SELECT properties.$browser FROM events")

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        assert collector.has_non_direct_fields is True

    def test_lazy_join_field_triggers_non_direct_flag(self):
        """Accessing session.$session_duration (lazy join) triggers has_non_direct_fields."""
        node, events_table_type = self._resolve_query("SELECT session.$session_duration FROM events")

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        assert collector.has_non_direct_fields is True

    def test_session_id_from_events_is_direct_column(self):
        """$session_id on events is a direct column (not a property access)."""
        node, events_table_type = self._resolve_query("SELECT `$session_id` FROM events")

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        # $session_id is a direct column on events table
        assert "$session_id" in collector.collected_fields
        assert collector.has_non_direct_fields is False

    def test_poe_properties_collected_as_person_properties(self):
        """poe.properties (VirtualTable) resolves to database column person_properties."""
        node, events_table_type = self._resolve_query("SELECT poe.properties FROM events")

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        assert "person_properties" in collector.collected_fields
        assert collector.has_non_direct_fields is False

    def test_poe_id_collected_as_person_id(self):
        """poe.id (VirtualTable) resolves to database column person_id."""
        node, events_table_type = self._resolve_query("SELECT poe.id FROM events")

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        assert "person_id" in collector.collected_fields
        assert collector.has_non_direct_fields is False

    def test_poe_created_at_collected_as_person_created_at(self):
        """poe.created_at (VirtualTable) resolves to database column person_created_at."""
        node, events_table_type = self._resolve_query("SELECT poe.created_at FROM events")

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        assert "person_created_at" in collector.collected_fields
        assert collector.has_non_direct_fields is False

    def test_poe_field_type_has_virtual_table_type(self):
        """Collected poe field has VirtualTableType as its table_type."""
        node, events_table_type = self._resolve_query("SELECT poe.properties FROM events")

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        field_type = collector.collected_fields["person_properties"]
        assert isinstance(field_type.table_type, ast.VirtualTableType)

    def test_poe_mixed_with_direct_columns(self):
        """VirtualTable fields and direct columns are both collected."""
        node, events_table_type = self._resolve_query("SELECT event, poe.id, timestamp FROM events")

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        assert "event" in collector.collected_fields
        assert "person_id" in collector.collected_fields
        assert "timestamp" in collector.collected_fields
        assert collector.has_non_direct_fields is False

    def test_poe_revenue_analytics_lazy_join_triggers_non_direct(self):
        """poe.revenue_analytics is a LazyJoin inside VirtualTable — triggers non-direct flag."""
        node, events_table_type = self._resolve_query("SELECT poe.revenue_analytics.revenue FROM events")

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        assert collector.has_non_direct_fields is True


class TestSavedQueryWithLazyJoins(BaseTest):
    """Tests for predicate pushdown with SavedQuery views that contain lazy joins.

    SavedQuery views (e.g., revenue_analytics) may contain queries with lazy joins
    (like events.person.distinct_id). When these views are expanded during resolve_types,
    the lazy joins should be fully resolved before predicate pushdown runs.
    """

    def setUp(self):
        super().setUp()
        from posthog.hogql.database.database import Database
        from posthog.hogql.database.models import IntegerDatabaseField, SavedQuery, StringDatabaseField, TableNode

        self.database = Database.create_for(team=self.team)

        # Create a SavedQuery that contains a query with lazy joins
        # This simulates what revenue_analytics views do
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

        # Add the saved query to the database using the proper table structure
        self.database.tables.add_child(TableNode(name="test_events_with_person", table=self.saved_query))

        self.context = HogQLContext(
            team_id=self.team.pk,
            database=self.database,
            enable_select_queries=True,
        )

    def test_saved_query_with_lazy_joins_and_session_join(self):
        """Query from SavedQuery that internally uses lazy joins should resolve properly."""

        # Need to set team on context for persons table join to work
        self.context.team = self.team

        query_str = "SELECT event, person_id, session_duration FROM test_events_with_person"

        # Use the full pipeline
        query, prepared_ast = prepare_and_print_ast(
            parse_select(query_str),
            self.context,
            "clickhouse",
        )

        # Should complete without error - verifies lazy joins are fully resolved
        assert "SELECT" in query
