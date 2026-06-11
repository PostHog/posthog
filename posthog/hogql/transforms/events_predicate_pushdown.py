from typing import cast

import structlog

from posthog.schema import HogQLQueryModifiers, PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import LimitContext, get_max_limit_for_context
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, FieldTraverser
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import EventsPredicatePushdownExtractor
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.printer.base import resolve_field_type
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.clickhouse.materialized_columns import TablesWithMaterializedColumns, get_materialized_column_for_property
from posthog.clickhouse.property_groups import property_groups
from posthog.models.property import PropertyName, TableColumn
from posthog.settings import TEST

logger = structlog.get_logger(__name__)


def events_pushdown_enabled(modifiers: HogQLQueryModifiers) -> bool:
    """Enabled when explicitly on, or unset under TEST. Shared by the call site and the transform."""
    return bool(modifiers.pushDownPredicates or (modifiers.pushDownPredicates is None and TEST))


def _printer_top_level_select_ids(node: _T_AST) -> set[int]:
    """Selects the printer will inject a top-level LIMIT into: the root, or the direct SelectQuery branches of
    the outermost union. Nested-union branches are excluded; they'd get an inner LIMIT with no outer cap."""
    if isinstance(node, ast.SelectQuery):
        return {id(node)}
    if isinstance(node, ast.SelectSetQuery):
        return {id(branch) for branch in node.select_queries() if isinstance(branch, ast.SelectQuery)}
    return set()


def apply_events_predicate_pushdown(
    node: _T_AST,
    context: HogQLContext,
) -> _T_AST:
    """Apply predicate pushdown to events tables with lazy joins. Mutates the AST in place; returns it."""
    top_level_select_ids = _printer_top_level_select_ids(node)
    EventsPredicatePushdownTransform(context=context, top_level_select_ids=top_level_select_ids).visit(node)
    return node


class SelectAliasInliner(CloningVisitor):
    """Inlines SELECT-alias references in a pushed predicate so the full aliased expression is carried into the
    subquery, not the bare name (which would re-bind to the raw column and drop the wrapper)."""

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
    """Detects any unresolved LazyJoinType / LazyTableType; pushdown bails if found (the subquery won't have those joins)."""

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
        if isinstance(query_type, ast.SelectSetQueryType):
            return False
        for table_type in query_type.tables.values():
            if self._check_table_type_for_lazy(table_type):
                return True
        for table_type in query_type.anonymous_tables:
            if self._check_table_type_for_lazy(table_type):
                return True
        return False


class EventsFieldCollector(TraversingVisitor):
    """Collects the direct events columns a query references (with resolved FieldTypes, so the subquery can be
    built without re-running resolve_types) and flags non-direct fields / lazy joins that block pushdown."""

    def __init__(self, target_table: ast.TableType | ast.TableAliasType, context: HogQLContext):
        super().__init__()
        self.target_table = target_table
        self.context = context
        self.collected_fields: dict[str, ast.FieldType] = {}
        self.materialized_columns: set[str] = set()
        self._group_covered_field_ids: set[int] = set()
        self.has_non_direct_fields = False

    def visit_field(self, node: ast.Field):
        super().visit_field(node)

        # Already exposed via its property-group Map column (see visit_call), so skip the redundant blob.
        if id(node) in self._group_covered_field_ids:
            return

        field_type = node.type

        # events.properties.$foo: unwrap to the base column so we collect/re-type it for the inner table.
        property_type = field_type if isinstance(field_type, ast.PropertyType) else None
        if property_type is not None:
            field_type = property_type.field_type

        if isinstance(field_type, ast.FieldType):
            table_type = field_type.table_type

            if self._type_references_lazy_join(table_type):
                self.has_non_direct_fields = True
                return

            if self._matches_target_table(table_type):
                # Expose the physical mat/dmat/group column the printer reads, not the slow `properties` blob;
                # falls through to the blob if the property isn't materialized.
                if property_type is not None and self._collect_materialized_column(property_type, field_type):
                    return

                db_column_name = self._get_database_column_name(field_type)
                if db_column_name:
                    self.collected_fields[db_column_name] = field_type
                else:
                    self.has_non_direct_fields = True

    def visit_call(self, node: ast.Call):
        # Expose the property-group Map column for an OPTIMIZED JSONHas(properties, 'k') before recursing, so
        # visit_field can skip the redundant blob. Mirrors ClickHousePrinter._get_optimized_property_group_call.
        group_column = self._optimized_json_has_group_column(node)
        if group_column is not None:
            self.materialized_columns.add(group_column)
            covered = node.args[0]
            while isinstance(covered, ast.Alias):
                covered = covered.expr
            if isinstance(covered, ast.Field):
                self._group_covered_field_ids.add(id(covered))
        super().visit_call(node)

    def _optimized_json_has_group_column(self, node: ast.Call) -> str | None:
        """The property-group Map column an OPTIMIZED `JSONHas(<events properties>, <const>)` reads, else None."""
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
        """Record the physical column the printer reads for this event property; False (collect the raw blob) when none."""
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
        """The single physical column the printer reads for events.<field>.<property>, or None. Mirrors
        BasePrinter._get_all_materialized_property_sources' priority (static column, dmat slot, first group column)."""
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
        try:
            resolved = field_type.resolve_database_field(self.context)
            if isinstance(resolved, FieldTraverser):
                return None
            if isinstance(resolved, DatabaseField):
                return resolved.name
            return None
        except Exception as err:
            # Fail-safe: treat any resolution failure as non-direct and decline; debug-logged so a resolver
            # regression silently disabling pushdown stays visible.
            logger.debug("events_predicate_pushdown_field_resolution_failed", error=str(err))
            return None

    def _matches_target_table(self, table_type: ast.Type | None) -> bool:
        if table_type is None:
            return False

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
        return table_type is self.target_table or unwrapped is target


class _ShortCircuitBlockerFinder(TraversingVisitor):
    """Finds aggregate or window functions, which consume the whole result before a LIMIT applies. Does not
    recurse into subqueries: only this query level's own expressions matter for its own LIMIT."""

    def __init__(self):
        super().__init__()
        self.found = False

    def visit(self, node):
        if not self.found:
            super().visit(node)

    def visit_select_query(self, node: ast.SelectQuery):
        pass

    def visit_window_function(self, node: ast.WindowFunction):
        self.found = True

    def visit_call(self, node: ast.Call):
        if find_hogql_aggregation(node.name):
            self.found = True
        else:
            super().visit_call(node)


class EventsPredicatePushdownTransform(TraversingVisitor):
    """Pushes events WHERE/PREWHERE predicates into a pre-filtering subquery:
    `FROM events` -> `FROM (SELECT <needed cols> FROM events WHERE <predicates>) AS events`.

    Runs after resolve_lazy_tables and applies bottom-up so nested `FROM events` subqueries benefit too."""

    # Join types across which moving an events PREDICATE is result-safe (they preserve the events/left side).
    # Broader than _all_joins_preserve_every_row (LEFT only): INNER / CROSS are predicate-safe but can drop an
    # events row, so they pass here yet decline at _safe_inner_limit (the single-rule gate always needs it).
    _SAFE_JOIN_TYPES = {"JOIN", "INNER JOIN", "LEFT JOIN", "LEFT OUTER JOIN", "CROSS JOIN"}

    def __init__(
        self,
        context: HogQLContext,
        top_level_select_ids: set[int] | None = None,
    ):
        super().__init__()
        self.context = context
        self.top_level_select_ids = top_level_select_ids or set()

    def visit_select_query(self, node: ast.SelectQuery):
        super().visit_select_query(node)  # bottom-up: visit subqueries first

        if self._should_apply_pushdown(node):
            try:
                decline_reason = self._apply_pushdown(node)
            except Exception as err:
                # Pure optimization: any unexpected failure must leave the query untouched, not break it.
                # _apply_pushdown mutates node only after every check passes, so a raise leaves it unchanged.
                logger.warning("events_predicate_pushdown_unexpected_error", error=str(err), exc_info=True)
                return
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

        # Collect needed columns before extracting/mutating predicates, so we can bail before touching
        # node.where and never drop a pushable predicate.
        collector = self._collect_needed_columns(node, events_table_type)
        if collector is None or (not collector.collected_fields and not collector.materialized_columns):
            return "no_collectable_columns"

        # Classify a WHERE field that resolves to an alias by what the alias references (e.g. `f(session.x) AS
        # event` must not be pushed by name).
        select_aliases = {expr.alias: expr.expr for expr in node.select if isinstance(expr, ast.Alias)}

        # Split without mutating node yet, so any bail below leaves the original predicates intact.
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

        # PREWHERE is valid only on a physical scan, not a subquery. A fully-pushable PREWHERE moves into the
        # inner scan; a residual one would have to stay on the outer subquery (invalid), so bail.
        if new_prewhere is not None:
            return "prewhere_not_fully_pushable"

        if inner_from_where is None and inner_from_prewhere is None:
            return "no_pushable_predicates"

        inner_where = self._prepare_inner_predicate(inner_from_where, select_aliases)
        inner_prewhere = self._prepare_inner_predicate(inner_from_prewhere, select_aliases)

        # The optimization only pays off when a LIMIT can short-circuit the events read. Predicates + an inner
        # LIMIT beat the flat query for every column type; predicates-only regresses for the raw blob, and
        # ORDER BY blocks the inner LIMIT. So push the inner LIMIT when result-equivalent, else decline.
        inner_limit = self._safe_inner_limit(node, new_where, new_prewhere)
        if inner_limit is None:
            return "no_short_circuitable_limit"

        # Build the subquery from the outer query's resolved types. The inner events table keeps the outer
        # alias so the pushed predicates resolve against it; the printer injects the per-table team_id guard.
        events_subquery = self._build_typed_subquery(
            collector.collected_fields,
            collector.materialized_columns,
            events_table_type,
            inner_where,
            inner_prewhere,
            alias=node.select_from.alias,
            limit=inner_limit,
        )
        if events_subquery is None:
            return "subquery_build_failed"
        subquery_type = events_subquery.type
        assert subquery_type is not None

        # Commit: drop the pushed predicates and swap the events table for the subquery, keeping the alias.
        node.where = new_where
        node.prewhere = new_prewhere
        original_alias = node.select_from.alias
        new_alias = original_alias or "events"
        node.select_from.table = events_subquery
        node.select_from.alias = new_alias

        # Outer field refs keep their original types and resolve against the alias by name.
        # TODO: re-point outer field refs so query metadata reflects the rewrite.
        node.select_from.type = ast.SelectQueryAliasType(
            alias=new_alias,
            select_query_type=subquery_type,
        )
        return None

    def _should_apply_pushdown(self, node: ast.SelectQuery) -> bool:
        """Eligible when the query selects FROM events directly (no SAMPLE), has a WHERE/PREWHERE, has joins,
        has an effective LIMIT, and does not aggregate / DISTINCT / window (those read the whole set regardless
        of the LIMIT, so the pre-filter would be pure overhead)."""
        return (
            events_pushdown_enabled(self.context.modifiers)
            and node.select_from is not None
            and node.select_from.sample is None
            and self._from_is_events_table(node.select_from)
            and (node.where is not None or node.prewhere is not None)
            and node.select_from.next_join is not None
            and self._has_effective_limit(node)
            and not self._forces_full_event_read(node)
        )

    def _has_effective_limit(self, node: ast.SelectQuery) -> bool:
        """A top-level select counts (the printer injects a cap <= MAX_SELECT_RETURNED_ROWS); a nested select
        counts only with an explicit LIMIT. Contexts that disable the cap (limit_top_select=False) decline."""
        if not self.context.limit_top_select:
            return False
        return id(node) in self.top_level_select_ids or node.limit is not None

    def _forces_full_event_read(self, node: ast.SelectQuery) -> bool:
        """True if the query consumes the whole filtered event set before its LIMIT applies. GROUP BY, DISTINCT,
        and aggregate / window functions (incl. in ORDER BY / HAVING / QUALIFY) block the short-circuit; a plain
        `ORDER BY <column>` does not."""
        if node.group_by or node.distinct:
            return True
        finder = _ShortCircuitBlockerFinder()
        for expr in (*node.select, node.having, node.qualify, *(node.order_by or [])):
            if expr is not None:
                finder.visit(expr)
        return finder.found

    def _all_joins_preserve_every_row(self, node: ast.SelectQuery) -> bool:
        """True if every events row yields >= 1 output row (all joins LEFT [OUTER]); an INNER / CROSS join could drop one."""
        join = node.select_from.next_join if node.select_from is not None else None
        while join is not None:
            if join.join_type not in ("LEFT JOIN", "LEFT OUTER JOIN"):
                return False
            join = join.next_join
        return True

    def _safe_inner_limit(
        self, node: ast.SelectQuery, residual_where: ast.Expr | None, residual_prewhere: ast.Expr | None
    ) -> ast.Constant | None:
        """The LIMIT to push into the events subquery, or None if pushing it would change results.

        Safe only when nothing after the events scan can drop or reorder rows: no ORDER BY / LIMIT BY / ARRAY
        JOIN / WITH TIES / percent, no residual outer predicate, all joins LEFT. Then the first `offset + limit`
        events cover the outer slice. The pushed value is the explicit LIMIT capped at (or, when absent,
        replaced by) the context cap the printer applies to a top-level select, so the inner scan never reads
        rows the capped outer slice can't emit.
        """
        if (
            node.order_by is not None
            or node.limit_by is not None
            or node.array_join_list is not None
            or node.limit_with_ties
            or node.limit_percent
        ):
            return None
        if residual_where is not None or residual_prewhere is not None:
            return None
        if not self._all_joins_preserve_every_row(node):
            return None
        offset = 0
        if node.offset is not None:
            if not isinstance(node.offset, ast.Constant) or not isinstance(node.offset.value, int):
                return None
            offset = node.offset.value
        # Derive the cap from limit_context (not a hardcoded MAX_SELECT_RETURNED_ROWS) so larger-cap contexts
        # (EXPORT / HEATMAPS / RETENTION) aren't under-capped, which would drop rows.
        cap = (
            get_max_limit_for_context(self.context.limit_context or LimitContext.QUERY)
            if self._is_top_level(node)
            else None
        )
        if isinstance(node.limit, ast.Constant) and isinstance(node.limit.value, int):
            limit_value = min(node.limit.value, cap) if cap is not None else node.limit.value
            return ast.Constant(value=limit_value + offset)
        # No explicit LIMIT: only a top-level select is safe (the printer injects its cap as the outer LIMIT).
        if cap is not None:
            return ast.Constant(value=cap + offset)
        return None

    def _is_top_level(self, node: ast.SelectQuery) -> bool:
        return id(node) in self.top_level_select_ids

    def _from_is_events_table(self, join_expr: ast.JoinExpr) -> bool:
        """True when the FROM resolves directly to the physical events table (not a subquery). Checking the
        resolved type also matches the qualified `FROM posthog.events`, which a chain comparison misses."""
        table_type: ast.Type | None = join_expr.type
        while isinstance(table_type, (ast.TableAliasType, ast.VirtualTableType)):
            table_type = table_type.table_type
        return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)

    def _collect_joined_aliases(self, node: ast.SelectQuery) -> set[str]:
        """Aliases from the JOIN chain, or an empty set if any join uses an unsafe type (causing the caller to bail)."""
        aliases: set[str] = set()
        join = node.select_from.next_join if node.select_from else None
        while join is not None:
            # A missing join_type is unreachable today but treated as unsafe rather than safe.
            if join.join_type is None or join.join_type not in self._SAFE_JOIN_TYPES:
                return set()
            if join.alias:
                aliases.add(join.alias)
            join = join.next_join
        return aliases

    def _collect_needed_columns(
        self, node: ast.SelectQuery, events_table_type: ast.TableType | ast.TableAliasType
    ) -> EventsFieldCollector | None:
        """Collect the events columns the outer query references; None if it can't be pushed (lazy or non-direct fields)."""
        lazy_detector = LazyTypeDetector()
        lazy_detector.visit(node)
        if lazy_detector.found_lazy_type:
            return None

        collector = EventsFieldCollector(events_table_type, self.context)
        collector.visit(node)

        if collector.has_non_direct_fields:
            return None

        return collector

    def _prepare_inner_predicate(self, expr: ast.Expr | None, select_aliases: dict[str, ast.Expr]) -> ast.Expr | None:
        """Ready a pushed predicate for the inner subquery (inline SELECT-alias refs, clone), or None if there is none."""
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
        limit: ast.Constant | None = None,
    ) -> ast.SelectQuery | None:
        """Build the subquery from the outer query's resolved FieldTypes (avoiding resolve_types, which might
        re-resolve lazy joins). Keeps the outer events alias so pushed predicates and the SELECT list match."""
        base_table_type: ast.Type = events_table_type
        if isinstance(base_table_type, ast.TableAliasType):
            base_table_type = base_table_type.table_type
        if not isinstance(base_table_type, ast.TableType):
            return None

        inner_table_type = self._inner_table_type_with_materialized_columns(base_table_type, materialized_columns)
        ref_table_type: ast.TableType | ast.TableAliasType = (
            ast.TableAliasType(alias=alias, table_type=inner_table_type) if alias else inner_table_type
        )

        # One aliased Field per column, so names survive even if PropertySwapper rewrites the inner expr.
        select_fields: list[ast.Expr] = []
        columns_in_scope: dict[str, ast.Type] = {}

        for col_name in sorted(collected_fields.keys()):
            original_field_type = collected_fields[col_name]

            if isinstance(original_field_type.table_type, ast.VirtualTableType):
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

        # Expose the raw physical mat/dmat/group columns so the printer's outer references resolve against the
        # subquery alias; the outer query re-applies the property semantics.
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
            limit=limit,
            type=select_query_type,
        )

    def _inner_table_type_with_materialized_columns(
        self, base_table_type: ast.TableType, materialized_columns: set[str]
    ) -> ast.TableType:
        """Inner events table type augmented with synthetic DatabaseFields for the materialized columns (physical
        ClickHouse columns, not HogQL schema fields). Uses a copy; the shared table object is never mutated."""
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
