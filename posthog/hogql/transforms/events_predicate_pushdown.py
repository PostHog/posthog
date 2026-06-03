from typing import cast

import structlog

from posthog.schema import PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, FieldTraverser
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import EventsPredicatePushdownExtractor
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.printer.base import resolve_field_type
from posthog.hogql.resolver_utils import extract_select_queries
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.clickhouse.materialized_columns import TablesWithMaterializedColumns, get_materialized_column_for_property
from posthog.clickhouse.property_groups import property_groups
from posthog.models.property import PropertyName, TableColumn
from posthog.settings import TEST

logger = structlog.get_logger(__name__)


def apply_events_predicate_pushdown(
    node: _T_AST,
    context: HogQLContext,
) -> _T_AST:
    """Apply predicate pushdown to events tables with lazy joins.

    The transform modifies the AST in place but also returns it for chaining.
    """
    # The outermost select queries always get a top-level LIMIT injected — the executor's _apply_limit
    # default, or the printer's limit_top_select cap of MAX_SELECT_RETURNED_ROWS — even when the user wrote
    # none. Both target exactly the extract_select_queries() set and cap at a value in the beneficial range,
    # so the gate treats these as guaranteed-limited regardless of execution path. (limit_top_select runs
    # after this transform, so the limit isn't on the AST here yet — hence the precomputed set.)
    top_level_select_ids = (
        {id(select) for select in extract_select_queries(node)}
        if isinstance(node, (ast.SelectQuery, ast.SelectSetQuery))
        else set()
    )
    EventsPredicatePushdownTransform(
        context=context, dialect="clickhouse", top_level_select_ids=top_level_select_ids
    ).visit(node)
    return node


class SelectAliasInliner(CloningVisitor):
    """Replaces references to SELECT-list aliases with the alias's own expression.

    A pushed predicate referencing a SELECT alias (e.g. `WHERE c > 0` with `lower(events.event) AS c`) must
    carry the full expression into the subquery; otherwise the bare name would re-bind to the raw column and
    drop the wrapper, changing results.

    Known limitation: a self-referential `toTimeZone(timestamp, 'UTC') AS timestamp` filter keeps a
    field-side `toTimeZone` in the subquery (weaker partition pruning, identical results; ClickHouse still
    prunes via monotonic-function handling). The common bare `WHERE timestamp >= ...` shape is unaffected.
    """

    def __init__(self, select_aliases: dict[str, ast.Expr]):
        super().__init__(clear_types=False)
        self.select_aliases = select_aliases
        self._resolving: set[str] = set()

    def visit_field(self, node: ast.Field):
        alias = node.type.alias if isinstance(node.type, ast.FieldAliasType) else None
        if alias is not None and alias in self.select_aliases and alias not in self._resolving:
            self._resolving.add(alias)
            try:
                return self.visit(clone_expr(self.select_aliases[alias], clear_types=False))
            finally:
                self._resolving.discard(alias)
        return super().visit_field(node)


class LazyTypeDetector(TraversingVisitor):
    """Detects any LazyJoinType / LazyTableType reference (on Field, JoinExpr, Alias, SelectQuery).

    Pushdown bails if any remain: the inner subquery won't have those joins.
    """

    def __init__(self):
        super().__init__()
        self.found_lazy_type = False

    def visit_field(self, node: ast.Field):
        super().visit_field(node)
        if node.type is not None and self._check_type_for_lazy(node.type):
            self.found_lazy_type = True

    def visit_join_expr(self, node: ast.JoinExpr):
        super().visit_join_expr(node)
        if node.type is not None and self._check_type_for_lazy(node.type):
            self.found_lazy_type = True

    def visit_alias(self, node: ast.Alias):
        super().visit_alias(node)
        if node.type is not None and self._check_type_for_lazy(node.type):
            self.found_lazy_type = True

    def _check_type_for_lazy(self, field_type: ast.Type) -> bool:
        """Recursively check if a type contains lazy references."""
        if isinstance(field_type, ast.LazyJoinType):
            return True
        if isinstance(field_type, ast.LazyTableType):
            return True
        if isinstance(field_type, ast.FieldType):
            return self._check_table_type_for_lazy(field_type.table_type)
        if isinstance(field_type, ast.PropertyType):
            return self._check_type_for_lazy(field_type.field_type)
        if isinstance(field_type, ast.SelectQueryAliasType):
            if field_type.select_query_type is not None:
                return self._check_select_query_type_for_lazy(field_type.select_query_type)
        return False

    def _check_table_type_for_lazy(self, table_type: ast.Type | None) -> bool:
        """Check if a table type references a lazy join."""
        if table_type is None:
            return False
        if isinstance(table_type, ast.LazyJoinType):
            return True
        if isinstance(table_type, ast.LazyTableType):
            return True
        if isinstance(table_type, ast.TableAliasType):
            return self._check_table_type_for_lazy(table_type.table_type)
        if isinstance(table_type, ast.SelectQueryAliasType):
            if table_type.select_query_type is not None:
                return self._check_select_query_type_for_lazy(table_type.select_query_type)
        return False

    def _check_select_query_type_for_lazy(self, query_type: ast.SelectQueryType | ast.SelectSetQueryType) -> bool:
        """Check if a select query type has lazy references in its tables."""
        if isinstance(query_type, ast.SelectSetQueryType):
            return False  # union subqueries aren't inspected here
        for table_type in query_type.tables.values():
            if self._check_table_type_for_lazy(table_type):
                return True
        for table_type in query_type.anonymous_tables:
            if self._check_table_type_for_lazy(table_type):
                return True
        return False


class EventsFieldCollector(TraversingVisitor):
    """Collects the direct events columns a query references, with their resolved FieldTypes so the inner
    subquery can be built without re-running resolve_types. Flags non-direct fields / lazy joins that block
    safe pushdown.
    """

    def __init__(self, target_table: ast.TableType | ast.TableAliasType, context: HogQLContext):
        super().__init__()
        self.target_table = target_table
        self.context = context
        self.collected_fields: dict[str, ast.FieldType] = {}  # db column name -> resolved FieldType
        # Physical mat/dmat/property-group columns the printer reads; exposed via synthetic DatabaseFields.
        self.materialized_columns: set[str] = set()
        # ids of bare `properties` Fields already covered by an OPTIMIZED JSONHas group rewrite (skip the blob).
        self._group_covered_field_ids: set[int] = set()
        self.has_non_direct_fields = False

    def visit_field(self, node: ast.Field):
        super().visit_field(node)

        # Covered by an OPTIMIZED JSONHas group rewrite (see visit_call): the printer reads the Map column,
        # not the blob, so don't also project `properties` for it.
        if id(node) in self._group_covered_field_ids:
            return

        field_type = node.type

        # events.properties.$foo: unwrap to the base column so we collect/re-type it for the inner table.
        property_type = field_type if isinstance(field_type, ast.PropertyType) else None
        if property_type is not None:
            field_type = property_type.field_type

        if isinstance(field_type, ast.FieldType):
            table_type = field_type.table_type

            # A lazy-join field (e.g. events.poe.distinct_id) won't exist in the inner subquery.
            if self._type_references_lazy_join(table_type):
                self.has_non_direct_fields = True
                return

            if self._matches_target_table(table_type):
                # Expose the physical mat/dmat/group column the printer reads (not the ~100x-slower
                # `properties` blob); falls through to collecting the blob if the property isn't materialized.
                if property_type is not None and self._collect_materialized_column(property_type, field_type):
                    return

                db_column_name = self._get_database_column_name(field_type)
                if db_column_name:
                    self.collected_fields[db_column_name] = field_type
                else:
                    self.has_non_direct_fields = True  # non-direct field (FieldTraverser, etc.); can't push

    def visit_call(self, node: ast.Call):
        # Expose the property-group Map column for an OPTIMIZED JSONHas(properties, 'k') (its arg is a bare
        # FieldType, so visit_field's property path never sees it). Done before recursing so visit_field can
        # skip the redundant blob projection. Mirrors ClickHousePrinter._get_optimized_property_group_call.
        group_column = self._optimized_json_has_group_column(node)
        if group_column is not None:
            self.materialized_columns.add(group_column)
            covered = node.args[0]  # mark the underlying Field (may be Alias-wrapped) so visit_field skips it
            while isinstance(covered, ast.Alias):
                covered = covered.expr
            if isinstance(covered, ast.Field):
                self._group_covered_field_ids.add(id(covered))
        super().visit_call(node)

    def _optimized_json_has_group_column(self, node: ast.Call) -> str | None:
        """The property-group Map column an OPTIMIZED `JSONHas(<events properties>, <const>)` reads, else None.

        Mirrors ClickHousePrinter._get_property_group_source_for_field: gated on OPTIMIZED only (not
        materializationMode), returning the first property-group column for the key.
        """
        if self.context.modifiers.propertyGroupsMode != PropertyGroupsMode.OPTIMIZED:
            return None
        if node.name != "JSONHas" or len(node.args) != 2 or not isinstance(node.args[1], ast.Constant):
            return None
        field_type = resolve_field_type(node.args[0])
        if not isinstance(field_type, ast.FieldType) or not self._matches_target_table(field_type.table_type):
            return None
        resolved = self._resolve_events_table_and_column(field_type)
        if resolved is None:
            return None
        table_name, field_name = resolved
        for group_column in property_groups.get_property_group_columns(table_name, field_name, str(node.args[1].value)):
            return group_column
        return None

    def _resolve_events_table_and_column(self, field_type: ast.FieldType) -> tuple[str, str] | None:
        """(events table name, db column name) for a direct column on the target events table, else None."""
        field_name = self._get_database_column_name(field_type)
        if field_name is None:
            return None
        table = field_type.table_type
        while isinstance(table, (ast.TableAliasType, ast.VirtualTableType)):
            table = table.table_type
        if not isinstance(table, ast.TableType):
            return None
        return table.table.to_printed_hogql(), field_name

    def _collect_materialized_column(self, property_type: ast.PropertyType, base_field_type: ast.FieldType) -> bool:
        """Record the physical column the printer will read for this event property; return True if any.

        Returns False when the property has no materialized backing, so the caller collects the raw
        `properties` column for the JSONExtract path.
        """
        if self.context.modifiers.materializationMode == "disabled" or not property_type.chain:
            return False
        resolved = self._resolve_events_table_and_column(base_field_type)
        if resolved is None:
            return False
        table_name, field_name = resolved
        column = self._materialized_column_for_property(table_name, field_name, str(property_type.chain[0]))
        if column is None:
            return False
        self.materialized_columns.add(column)
        return True

    def _materialized_column_for_property(self, table_name: str, field_name: str, property_name: str) -> str | None:
        """The single physical column the ClickHouse printer reads for events.<field>.<property>, or None.

        Mirrors BasePrinter._get_all_materialized_property_sources' priority (static materialized column, then
        dmat slot, then first property-group Map column) using the same lookups, so the subquery exposes
        exactly the column the outer reference resolves to.
        """
        materialized_column = get_materialized_column_for_property(
            cast(TablesWithMaterializedColumns, table_name),
            cast(TableColumn, field_name),
            cast(PropertyName, property_name),
        )
        if materialized_column is not None:
            return materialized_column.name

        if self.context.property_swapper is not None and table_name == "events" and field_name == "properties":
            prop_info = self.context.property_swapper.event_properties.get(property_name)
            if prop_info and prop_info.get("dmat"):
                return prop_info["dmat"]

        if self.context.modifiers.propertyGroupsMode in (PropertyGroupsMode.ENABLED, PropertyGroupsMode.OPTIMIZED):
            for group_column in property_groups.get_property_group_columns(table_name, field_name, property_name):
                return group_column

        return None

    def _type_references_lazy_join(self, table_type: ast.Type | None) -> bool:
        """Check if a type references a lazy join anywhere in its chain."""
        if table_type is None:
            return False
        if isinstance(table_type, ast.LazyJoinType):
            return True
        if isinstance(table_type, ast.TableAliasType):
            return self._type_references_lazy_join(table_type.table_type)
        if isinstance(table_type, ast.LazyTableType):
            return True
        if isinstance(table_type, ast.VirtualTableType):
            return self._type_references_lazy_join(table_type.table_type)
        return False

    def _get_database_column_name(self, field_type: ast.FieldType) -> str | None:
        """Get the database column name for a field, or None if not a direct database field."""
        try:
            resolved = field_type.resolve_database_field(self.context)
            if isinstance(resolved, FieldTraverser):
                return None
            if isinstance(resolved, DatabaseField):
                return resolved.name
            return None
        except Exception as err:
            # Fail-safe: any resolution failure -> treat as non-direct and decline (pushdown is a pure
            # optimization). Debug-logged so a resolver regression silently disabling pushdown stays visible.
            logger.debug("events_predicate_pushdown_field_resolution_failed", error=str(err))
            return None

    def _matches_target_table(self, table_type: ast.Type | None) -> bool:
        """Check if a table type matches our target table."""
        if table_type is None:
            return False

        # Unwrap alias/virtual wrappers on both sides to the underlying TableType.
        unwrapped: ast.Type = table_type
        if isinstance(unwrapped, ast.TableAliasType):
            unwrapped = unwrapped.table_type
        if isinstance(unwrapped, ast.VirtualTableType):
            unwrapped = unwrapped.table_type
        if isinstance(unwrapped, ast.TableAliasType):
            unwrapped = unwrapped.table_type

        target: ast.Type = self.target_table
        if isinstance(target, ast.TableAliasType):
            target = target.table_type

        if isinstance(unwrapped, ast.TableType) and isinstance(target, ast.TableType):
            return unwrapped.table is target.table
        return table_type is self.target_table or unwrapped is target  # identity fallback


class _ShortCircuitBlockerFinder(TraversingVisitor):
    """Finds aggregate or window functions in an expression — constructs that consume the whole result
    before a LIMIT applies. Does not recurse into subqueries: only this query level's own SELECT/HAVING
    expressions determine whether its own LIMIT can short-circuit the events scan.
    """

    def __init__(self):
        super().__init__()
        self.found = False

    def visit(self, node):
        if not self.found:
            super().visit(node)

    def visit_select_query(self, node: ast.SelectQuery):
        pass  # a nested subquery's aggregation doesn't make this level read everything

    def visit_window_function(self, node: ast.WindowFunction):
        self.found = True

    def visit_call(self, node: ast.Call):
        if find_hogql_aggregation(node.name):
            self.found = True
        else:
            for arg in node.args:
                self.visit(arg)


class EventsPredicatePushdownTransform(TraversingVisitor):
    """Pushes events WHERE/PREWHERE predicates into a pre-filtering subquery:
    `FROM events` -> `FROM (SELECT <needed cols> FROM events WHERE <predicates>) AS events`.

    Runs after resolve_lazy_tables (lazy joins are real JoinExprs, aliases visible via next_join), and
    applies bottom-up so nested `FROM events` subqueries benefit too.
    """

    # Join types that preserve the events (left) side. RIGHT / FULL OUTER preserve the right side, so
    # pre-filtering events would turn matched rows into NULL-padded ones; exclude them.
    _SAFE_JOIN_TYPES = {"JOIN", "INNER JOIN", "LEFT JOIN", "LEFT OUTER JOIN", "CROSS JOIN"}

    def __init__(
        self,
        context: HogQLContext,
        dialect: HogQLDialect = "clickhouse",
        top_level_select_ids: set[int] | None = None,
    ):
        super().__init__()
        self.context = context
        self.dialect = dialect
        # ids of the outermost select queries — guaranteed to get a top-level LIMIT injected later.
        self.top_level_select_ids = top_level_select_ids or set()

    def visit_select_query(self, node: ast.SelectQuery):
        # Visit children (subqueries) first so pushdown is applied bottom-up.
        super().visit_select_query(node)

        if self._should_apply_pushdown(node):
            # _apply_pushdown returns a reason when it declines after passing the eligibility gate (None if
            # applied). Debug-logged so "eligible but silently not optimizing" (e.g. a resolver change that
            # disables pushdown) stays observable; the timing span alone can't tell applied from declined.
            decline_reason = self._apply_pushdown(node)
            if decline_reason is not None:
                logger.debug("events_predicate_pushdown_declined", reason=decline_reason)

    def _apply_pushdown(self, node: ast.SelectQuery) -> str | None:
        """Apply predicate pushdown to an eligible query. Returns a decline reason, or None if applied."""
        assert node.select_from is not None

        joined_aliases = self._collect_joined_aliases(node)
        if not joined_aliases:
            return "no_safe_joined_aliases"

        events_table_type = node.select_from.type
        if not isinstance(events_table_type, (ast.TableType, ast.TableAliasType)):
            return "from_not_table_type"

        # Collect needed columns BEFORE extracting/mutating predicates: captures the columns the outer query
        # reads through the subquery alias, and lets us bail before touching node.where so pushable predicates
        # are never dropped.
        collector = self._collect_needed_columns(node, events_table_type)
        if collector is None or (not collector.collected_fields and not collector.materialized_columns):
            return "no_collectable_columns"

        # SELECT-list aliases so the extractor can classify a WHERE field that resolves to an alias by
        # what the alias actually references (e.g. `f(session.x) AS event` must not be pushed by name).
        select_aliases = {expr.alias: expr.expr for expr in node.select if isinstance(expr, ast.Alias)}

        # Split WHERE/PREWHERE without mutating node yet, so the pushdown stays atomic (any bail below leaves the original predicates intact).
        extractor = EventsPredicatePushdownExtractor(
            joined_table_aliases=joined_aliases,
            events_table_type=events_table_type,
            select_aliases=select_aliases,
        )

        inner_from_where: ast.Expr | None = None
        inner_from_prewhere: ast.Expr | None = None
        new_where = node.where
        new_prewhere = node.prewhere

        if node.where is not None:
            inner_from_where, new_where = extractor.get_pushdown_predicates(node.where)
        if node.prewhere is not None:
            inner_from_prewhere, new_prewhere = extractor.get_pushdown_predicates(node.prewhere)

        # PREWHERE is only valid on a physical MergeTree scan, not a subquery. A valid PREWHERE is events-only
        # (fully pushable) and moves into the inner subquery, staying a PREWHERE there. A non-pushable PREWHERE
        # predicate (a joined column / arrayJoin, already invalid as PREWHERE on the base table) would have to
        # stay on the outer subquery, which is invalid, so bail and let the original query fail itself.
        if new_prewhere is not None:
            return "prewhere_not_fully_pushable"

        if inner_from_where is None and inner_from_prewhere is None:
            return "no_pushable_predicates"

        # Prepare each pushed clause independently and keep WHERE vs PREWHERE separate so a pushed PREWHERE
        # stays a PREWHERE on the inner events scan.
        inner_where = self._prepare_inner_predicate(inner_from_where, select_aliases)
        inner_prewhere = self._prepare_inner_predicate(inner_from_prewhere, select_aliases)

        # Build the subquery with explicit types (not resolve_types, which would re-resolve lazy joins). The
        # inner events table keeps the outer query's alias (e.g. `FROM events AS e`) so the pushed predicates,
        # which still reference that alias, resolve against it unchanged. The per-table team_id guard is
        # injected later by the printer.
        events_subquery = self._build_typed_subquery(
            collector.collected_fields,
            collector.materialized_columns,
            events_table_type,
            inner_where,
            inner_prewhere,
            alias=node.select_from.alias,
        )
        if events_subquery is None:
            return "subquery_build_failed"  # fail-safe: leave the query unchanged rather than emit broken SQL
        subquery_type = events_subquery.type
        assert subquery_type is not None  # _build_typed_subquery always sets it; checked before mutating node

        # All checks passed; commit: drop the pushed predicates from the outer query and swap the events
        # table for the subquery, keeping the original alias (default "events").
        node.where = new_where
        node.prewhere = new_prewhere
        original_alias = node.select_from.alias
        new_alias = original_alias or "events"
        node.select_from.table = events_subquery
        node.select_from.alias = new_alias

        # Mark the FROM as a subquery alias so the printer prints the subquery. Outer field refs keep their
        # original types, which is fine; they resolve against the alias by name.
        # TODO: re-point outer field refs so query metadata reflects the rewrite.
        node.select_from.type = ast.SelectQueryAliasType(
            alias=new_alias,
            select_query_type=subquery_type,
        )
        return None  # applied

    def _should_apply_pushdown(self, node: ast.SelectQuery) -> bool:
        """Check if this query is eligible for predicate pushdown.

        Applies to a query that:
        - selects FROM events directly (not a subquery), with no SAMPLE clause
        - has a WHERE or PREWHERE clause
        - has joins (lazy or explicit)
        - has an effective LIMIT (so pushing the predicate lets the LIMIT short-circuit the events scan), and
        - does not aggregate / DISTINCT / window (those read the whole filtered set regardless of the LIMIT,
          so the pre-filter subquery would be pure materialization overhead — a measured regression).
        """
        return (
            (self.context.modifiers.pushDownPredicates or (self.context.modifiers.pushDownPredicates is None and TEST))
            and node.select_from is not None
            and node.select_from.sample is None  # No SAMPLE clause
            and self._from_is_events_table(node.select_from)
            and (node.where is not None or node.prewhere is not None)
            and node.select_from.next_join is not None  # Has joins
            and self._has_effective_limit(node)
            and not self._forces_full_event_read(node)
        )

    def _has_effective_limit(self, node: ast.SelectQuery) -> bool:
        """The LIMIT can bound the events scan, so the pushdown lets it short-circuit early.

        An outermost select always gets a top-level LIMIT injected (<= MAX_SELECT_RETURNED_ROWS, in the
        beneficial range), so it counts regardless of what's on the AST right now. A nested subquery only
        counts if it carries an explicit LIMIT.
        """
        return id(node) in self.top_level_select_ids or node.limit is not None

    def _forces_full_event_read(self, node: ast.SelectQuery) -> bool:
        """True if the query consumes the whole filtered event set before its LIMIT applies.

        GROUP BY, DISTINCT, and aggregate / window functions all read every matching row before the LIMIT
        selects from the result, so the LIMIT can't short-circuit the events scan. The pushdown stays
        correct, but with nothing to short-circuit the pre-filter subquery is pure materialization overhead.
        """
        if node.group_by or node.distinct:
            return True
        finder = _ShortCircuitBlockerFinder()
        for expr in (*node.select, node.having):
            if expr is not None:
                finder.visit(expr)
        return finder.found

    def _from_is_events_table(self, join_expr: ast.JoinExpr) -> bool:
        """True when the FROM resolves directly to the physical events table (not a subquery).

        Checking the resolved table type rather than the field chain also matches the qualified form
        (`FROM posthog.events`), which a `chain == ["events"]` string comparison silently misses.
        """
        table_type: ast.Type | None = join_expr.type
        while isinstance(table_type, (ast.TableAliasType, ast.VirtualTableType)):
            table_type = table_type.table_type
        return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)

    def _collect_joined_aliases(self, node: ast.SelectQuery) -> set[str]:
        """Collect aliases from the JOIN chain.

        Returns an empty set if any join uses an unsafe type (e.g. RIGHT JOIN,
        FULL OUTER JOIN), which causes _apply_pushdown to bail out.
        """
        aliases: set[str] = set()
        join = node.select_from.next_join if node.select_from else None
        while join is not None:
            # Only push when the join type is provably safe. A missing join_type is unreachable today
            # (the parser always sets it on next_join entries) but is treated as unsafe rather than safe,
            # so an unverified join can never let us filter the preserved side of an unknown join.
            if join.join_type is None or join.join_type not in self._SAFE_JOIN_TYPES:
                return set()
            if join.alias:
                aliases.add(join.alias)
            join = join.next_join
        return aliases

    def _collect_needed_columns(
        self, node: ast.SelectQuery, events_table_type: ast.TableType | ast.TableAliasType
    ) -> EventsFieldCollector | None:
        """Walk the whole outer query and collect the events columns it references (SELECT, WHERE/PREWHERE,
        GROUP BY, ORDER BY, HAVING, JOIN constraints). Returns the collector, or None if it can't be pushed.
        """
        # Unresolved lazy types would break once we replace the FROM clause.
        lazy_detector = LazyTypeDetector()
        lazy_detector.visit(node)
        if lazy_detector.found_lazy_type:
            return None

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        # Non-direct fields may not exist in the subquery (e.g. a join constraint), so don't push.
        if collector.has_non_direct_fields:
            return None

        return collector

    def _prepare_inner_predicate(self, expr: ast.Expr | None, select_aliases: dict[str, ast.Expr]) -> ast.Expr | None:
        """Ready a pushed predicate for the inner subquery, or None if there is none.

        Inlines SELECT-alias references so the full expression is carried (not just the alias name, which
        would re-bind to the raw column and drop the wrapper). The predicate is otherwise moved unchanged:
        the inner subquery keeps the outer events alias, so references like `e.timestamp` / `e.properties.x`
        resolve against it as-is. A fresh clone keeps the subquery's copy independent of the outer query.
        """
        if expr is None:
            return None
        expr = SelectAliasInliner(select_aliases).visit(expr)
        return clone_expr(expr)

    def _build_typed_subquery(
        self,
        collected_fields: dict[str, ast.FieldType],
        materialized_columns: set[str],
        events_table_type: ast.TableType | ast.TableAliasType,
        where_clause: ast.Expr | None,
        prewhere_clause: ast.Expr | None = None,
        alias: str | None = None,
    ) -> ast.SelectQuery | None:
        """Build a subquery using the already-resolved types from the outer query.

        Uses the collected FieldTypes to build the subquery, avoiding the need to
        call resolve_types which might resolve HogQL abstract columns to lazy joins.

        When the outer query aliased events (`FROM events AS e`), the inner table keeps that alias so the
        pushed predicates resolve against it unchanged. The projection and scope reference the same aliased
        type, so the SELECT list prints `e.<col>` to match the aliased inner FROM.
        """
        # The subquery reads from the same physical events table the outer query did.
        base_table_type: ast.Type = events_table_type
        if isinstance(base_table_type, ast.TableAliasType):
            base_table_type = base_table_type.table_type  # may be a TableType or a LazyTableType
        if not isinstance(base_table_type, ast.TableType):
            return None  # shouldn't happen for valid events queries; bail rather than raise (pure optimization)

        inner_table_type = self._inner_table_type_with_materialized_columns(base_table_type, materialized_columns)
        # Field references (projection + scope) point at the aliased table when there is an alias, so they
        # print `e.<col>` against the aliased inner FROM; otherwise they print `events.<col>`.
        ref_table_type: ast.TableType | ast.TableAliasType = (
            ast.TableAliasType(alias=alias, table_type=inner_table_type) if alias else inner_table_type
        )

        # One aliased Field per column, so the names survive even if PropertySwapper rewrites the inner expr.
        select_fields: list[ast.Expr] = []
        columns_in_scope: dict[str, ast.Type] = {}

        for col_name in sorted(collected_fields.keys()):
            original_field_type = collected_fields[col_name]

            if isinstance(original_field_type.table_type, ast.VirtualTableType):
                # Recreate the VirtualTableType wrapping the inner table, keeping the HogQL field name.
                virtual_table_type = ast.VirtualTableType(
                    table_type=ref_table_type,
                    field=original_field_type.table_type.field,
                    virtual_table=original_field_type.table_type.virtual_table,
                )
                field_type = ast.FieldType(name=original_field_type.name, table_type=virtual_table_type)
            else:
                field_type = ast.FieldType(name=col_name, table_type=ref_table_type)

            field_node = ast.Field(chain=[col_name], type=field_type)
            alias_node = ast.Alias(alias=col_name, expr=field_node, type=field_type)
            select_fields.append(alias_node)
            columns_in_scope[col_name] = field_type

        # Expose the raw physical mat/dmat/group columns so the printer's outer references (e.g.
        # `e.mat_tier`, `has(e.properties_group_*, ...)`) resolve against the subquery alias; the
        # outer query re-applies the property semantics.
        for col_name in sorted(materialized_columns):
            if col_name in columns_in_scope:
                continue
            field_type = ast.FieldType(name=col_name, table_type=ref_table_type)
            field_node = ast.Field(chain=[col_name], type=field_type)
            select_fields.append(ast.Alias(alias=col_name, expr=field_node, type=field_type))
            columns_in_scope[col_name] = field_type

        events_field = ast.Field(chain=["events"], type=inner_table_type)
        select_from = ast.JoinExpr(table=events_field, alias=alias, type=ref_table_type)
        select_query_type = ast.SelectQueryType(columns=columns_in_scope, tables={alias or "events": ref_table_type})

        return ast.SelectQuery(
            select=select_fields,
            select_from=select_from,
            where=where_clause,
            prewhere=prewhere_clause,
            type=select_query_type,
        )

    def _inner_table_type_with_materialized_columns(
        self, base_table_type: ast.TableType, materialized_columns: set[str]
    ) -> ast.TableType:
        """Inner events table type, augmented with synthetic DatabaseFields for the materialized columns.

        Mat/dmat/property-group columns are physical ClickHouse columns, not HogQL schema fields, so they
        can't resolve as plain Fields without this. Uses a copy; the shared table object is never mutated.
        """
        synthetic_fields = {
            column: DatabaseField(name=column)
            for column in materialized_columns
            if not base_table_type.table.has_field(column)
        }
        if not synthetic_fields:
            return base_table_type
        augmented_table = base_table_type.table.model_copy(
            update={"fields": {**base_table_type.table.fields, **synthetic_fields}}
        )
        return ast.TableType(table=augmented_table)
