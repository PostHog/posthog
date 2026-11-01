"""Events subquery pushdown.

Moves outer filters and property reads into a plain events subquery, so the shards filter the scan and read keys as
columns instead of exporting whole rows:

    SELECT count(), countIf(properties.utm_source != '')
    FROM (SELECT * FROM events WHERE <p>)
    WHERE event = '$pageview' AND timestamp >= '2026-01-01'
    ->
    SELECT count(), countIf(properties__utm_source != '')
    FROM (SELECT *, properties.utm_source AS properties__utm_source
          FROM events WHERE <p> AND event = '$pageview' AND timestamp >= '2026-01-01')

ClickHouse builds the shard query from the AST and does not push an outer predicate into a Distributed subquery that
contains a JOIN. `SELECT * FROM events` always ends up with one, because the lazy-join pass adds the person-id override
join for `person_id`, so the shards receive the subquery bare and scan the whole team. On the native JSON events table
the exported `properties` blob is also rebuilt per row, and a key read on that text costs the whole column instead of
one subcolumn.

Two rewrites, each result-equivalent:

1. Every AND-conjunct of the outer WHERE that reads only columns the subquery exports straight from the events table
   (plain columns, and keys of its `properties` blob) moves into the subquery's WHERE. The subquery has to be a pure
   row filter over events (no DISTINCT, GROUP BY, aggregate, window, stream-dependent function, ARRAY JOIN, LIMIT,
   OFFSET, LIMIT BY, SAMPLE or JOIN), so filtering its input returns the same rows as filtering its output. The outer
   query may attach only INNER / LEFT / CROSS joins to it, which a filter on their left side commutes with, and must
   not read the stream itself (`rowNumberInAllBlocks()`), because an earlier filter changes what streams past.
2. Every remaining outer `properties.<key>` read of the subquery's blob column becomes a column of the subquery that
   reads the key from the events table, and the outer read points at that column. A bare read of the blob is left
   alone, so a consumer of the whole document still gets it.

A moved key read is lowered to a raw extract on the spot, as the lazy-join wrapper does, so it keeps the untyped
string value the outer read has today rather than the property-definition type a direct read gets: an outer
`toFloatOrZero(properties.amount)` would otherwise receive a Float and fail.

Runs after type resolution, before projection pruning (so a blob nobody reads anymore can be pruned) and before the
lazy-join pass (so the subquery is still a bare events scan). A pure optimization: an unexpected error leaves the
query untouched.
"""

from typing import TYPE_CHECKING, cast

import structlog

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, ExpressionField, StringJSONDatabaseField
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import (
    contains_in_cohort,
    contains_row_multiplying_function,
)
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.transforms.events_predicate_pushdown import SelectAliasInliner
from posthog.hogql.transforms.logical_property_lowering import lower_property_access
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

logger = structlog.get_logger(__name__)

# Join types a filter on their left side commutes with. A RIGHT, FULL, RIGHT SEMI / ANTI or PASTE join emits or drops
# rows depending on which left rows exist, so filtering the left side first changes the result.
_LEFT_FILTER_SAFE_JOIN_TYPES = frozenset({"JOIN", "INNER JOIN", "LEFT JOIN", "LEFT OUTER JOIN", "CROSS JOIN"})

# Functions whose value depends on the rows that streamed past them, so filtering the input earlier changes it. HogQL
# exposes the first two today; the rest are ClickHouse's remaining stream-dependent functions, listed so a future
# mapping keeps the guard.
_STREAM_DEPENDENT_FUNCTIONS = frozenset(
    {
        "rowNumberInBlock",
        "rowNumberInAllBlocks",
        "blockNumber",
        "blockSize",
        "neighbor",
        "runningAccumulate",
        "runningConcurrency",
        "runningDifference",
        "runningDifferenceStartingWithFirstValue",
    }
)

SubqueryFromType = ast.SelectQueryType | ast.SelectQueryAliasType


def events_subquery_pushdown_enabled(modifiers: "HogQLQueryModifiers") -> bool:
    """On unless a project turns it off. Unset means on, so the default stays out of the query cache key."""
    return modifiers.pushDownIntoEventsSubqueries is not False


def apply_events_subquery_pushdown(node: _T_AST, context: HogQLContext) -> _T_AST:
    """Mutates the AST in place; returns it."""
    EventsSubqueryPushdownTransform(context).visit(node)
    return node


def _conjuncts(expr: ast.Expr) -> list[ast.Expr]:
    if isinstance(expr, ast.And):
        return [conjunct for sub_expr in expr.exprs for conjunct in _conjuncts(sub_expr)]
    if isinstance(expr, ast.Call) and expr.name == "and":
        return [conjunct for sub_expr in expr.args for conjunct in _conjuncts(sub_expr)]
    return [expr]


def _and(exprs: list[ast.Expr]) -> ast.Expr | None:
    if not exprs:
        return None
    if len(exprs) == 1:
        return exprs[0]
    return ast.And(exprs=exprs)


def _is_events_table(table_type: ast.Type | None) -> bool:
    if isinstance(table_type, ast.TableAliasType):
        table_type = table_type.table_type
    return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)


def _output_name(expr: ast.Expr) -> str | None:
    if isinstance(expr, ast.Alias):
        return expr.alias
    if isinstance(expr, ast.Field) and isinstance(expr.type, ast.FieldType):
        return expr.type.name
    return None


class _ExportedColumns:
    """The columns a plain events subquery exports verbatim from the events table, by output name, and the reads an
    outer query can make of them: the events column behind a subquery column, or a raw key read off its blob."""

    def __init__(self, inner: ast.SelectQuery, from_type: SubqueryFromType, context: HogQLContext):
        self.from_type = from_type
        self.context = context
        self._columns: dict[str, ast.Field] = {}
        assert inner.select_from is not None
        events_type = inner.select_from.type
        for expr in inner.select:
            name = _output_name(expr)
            source = expr
            while isinstance(source, ast.Alias):
                source = source.expr
            if name is None or not isinstance(source, ast.Field):
                continue
            if not isinstance(source.type, ast.FieldType) or source.type.table_type is not events_type:
                continue
            database_field = source.type.resolve_database_field(context)
            if not isinstance(database_field, DatabaseField) or isinstance(database_field, ExpressionField):
                continue
            self._columns[name] = source

    def __bool__(self) -> bool:
        return bool(self._columns)

    def column(self, field_type: ast.FieldType) -> ast.Field | None:
        if field_type.table_type is not self.from_type:
            return None
        return self._columns.get(field_type.name)

    def key_read(self, property_type: ast.PropertyType) -> ast.Expr | None:
        source = self.column(property_type.field_type)
        if source is None or not isinstance(source.type, ast.FieldType):
            return None
        if not isinstance(source.type.resolve_database_field(self.context), StringJSONDatabaseField):
            return None
        read = ast.Field(
            chain=[*source.chain, *property_type.chain],
            type=ast.PropertyType(chain=list(property_type.chain), field_type=source.type),
        )
        return lower_property_access(read, self.context)


class _ConjunctRewriter(CloningVisitor):
    """Clones one outer WHERE conjunct with every read of the subquery re-pointed at the events column behind it.
    `blocked` is set when the conjunct reads anything else; `moved` counts the re-pointed reads."""

    def __init__(self, columns: _ExportedColumns):
        super().__init__(clear_types=False)
        self.columns = columns
        self.blocked = False
        self.moved = 0

    def visit_field(self, node: ast.Field) -> ast.Expr:
        replacement = self._events_read(node)
        if replacement is None:
            if not isinstance(node.type, ast.LambdaArgumentType):
                self.blocked = True
            return super().visit_field(node)
        self.moved += 1
        return replacement

    def _events_read(self, node: ast.Field) -> ast.Expr | None:
        if isinstance(node.type, ast.FieldType):
            source = self.columns.column(node.type)
            return clone_expr(source, clear_types=False) if source is not None else None
        if isinstance(node.type, ast.PropertyType):
            return self.columns.key_read(node.type)
        return None

    def visit_alias(self, node: ast.Alias) -> ast.Alias:
        # The resolver's hidden alias around a column read carries the read's type again; keep it in step.
        new_node = cast(ast.Alias, super().visit_alias(node))
        if isinstance(new_node.type, ast.FieldAliasType) and new_node.expr.type is not None:
            new_node.type = ast.FieldAliasType(alias=new_node.type.alias, type=new_node.expr.type)
        return new_node

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        # A nested select is its own scope and cannot read the outer FROM.
        return cast(ast.SelectQuery, clone_expr(node, clear_types=False))

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> ast.SelectSetQuery:
        return cast(ast.SelectSetQuery, clone_expr(node, clear_types=False))


class _KeyReadHoister(CloningVisitor):
    """Clones an outer expression with every `properties.<key>` read of the subquery's blob replaced by a read of a
    subquery column that extracts the key from the events table. `added` holds those columns, one per key path;
    `alias_type_updates` holds the alias types to re-point once the rewrite is committed, because the resolver shares
    them with the select scope's column and alias maps."""

    def __init__(self, columns: _ExportedColumns, taken_names: set[str]):
        super().__init__(clear_types=False)
        self.columns = columns
        self.added: dict[tuple[str, tuple[str | int, ...]], ast.Alias] = {}
        self.alias_type_updates: list[tuple[ast.FieldAliasType, ast.Type]] = []
        self._taken_names = set(taken_names)
        self._counter = 0

    def visit_field(self, node: ast.Field) -> ast.Expr:
        if not isinstance(node.type, ast.PropertyType):
            return super().visit_field(node)
        read = self.columns.key_read(node.type)
        if read is None:
            return super().visit_field(node)
        key = (node.type.field_type.name, tuple(node.type.chain))
        column = self.added.get(key)
        if column is None:
            name = self._name_for(key)
            column = ast.Alias(
                alias=name, expr=read, type=ast.FieldAliasType(alias=name, type=read.type or ast.UnknownType())
            )
            self.added[key] = column
        from_type = self.columns.from_type
        chain: list[str | int] = (
            [from_type.alias, column.alias] if isinstance(from_type, ast.SelectQueryAliasType) else [column.alias]
        )
        return ast.Field(chain=chain, type=ast.FieldType(name=column.alias, table_type=from_type))

    def _name_for(self, key: tuple[str, tuple[str | int, ...]]) -> str:
        column, path = key
        name = "__".join([column, *(str(link) for link in path)])
        while name in self._taken_names:
            name = f"__hoisted_{column}_{self._counter}"
            self._counter += 1
        self._taken_names.add(name)
        return name

    def visit_alias(self, node: ast.Alias) -> ast.Alias:
        new_node = cast(ast.Alias, super().visit_alias(node))
        if (
            isinstance(new_node.type, ast.FieldAliasType)
            and new_node.expr.type is not None
            and new_node.type.type is not new_node.expr.type
        ):
            self.alias_type_updates.append((new_node.type, new_node.expr.type))
        return new_node

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        return cast(ast.SelectQuery, clone_expr(node, clear_types=False))

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> ast.SelectSetQuery:
        return cast(ast.SelectSetQuery, clone_expr(node, clear_types=False))


class _RowStreamDependencyFinder(TraversingVisitor):
    """Finds an expression at this query level whose value depends on the whole input stream rather than on its own
    row: a stream-dependent function, and with `include_aggregates` an aggregate or window function too. A filter
    applied before such an expression changes its result, so it is not a filter on the output."""

    def __init__(self, *, include_aggregates: bool) -> None:
        super().__init__()
        self.include_aggregates = include_aggregates
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        pass

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        pass

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        if self.include_aggregates:
            self.found = True

    def visit_call(self, node: ast.Call) -> None:
        if node.name in _STREAM_DEPENDENT_FUNCTIONS or (self.include_aggregates and find_hogql_aggregation(node.name)):
            self.found = True
        else:
            super().visit_call(node)


def _depends_on_row_stream(exprs: list[ast.Expr | None], *, include_aggregates: bool) -> bool:
    finder = _RowStreamDependencyFinder(include_aggregates=include_aggregates)
    for expr in exprs:
        if expr is not None:
            finder.visit(expr)
    return finder.found


def _outer_expressions(outer: ast.SelectQuery) -> list[ast.Expr | None]:
    """Every expression slot of a select at its own level, join constraints included; joined tables are their own scope."""
    exprs: list[ast.Expr | None] = [
        *outer.select,
        outer.where,
        outer.prewhere,
        outer.having,
        outer.qualify,
        *(outer.group_by or []),
        *(outer.order_by or []),
        *(outer.array_join_list or []),
        outer.limit_by,
        *((outer.window_exprs or {}).values()),
    ]
    join = outer.select_from.next_join if outer.select_from is not None else None
    while join is not None:
        if join.constraint is not None:
            exprs.append(join.constraint.expr)
        join = join.next_join
    return exprs


class EventsSubqueryPushdownTransform(TraversingVisitor):
    """Applies the two rewrites to every select whose leftmost FROM is a plain events subquery, bottom-up."""

    def __init__(self, context: HogQLContext):
        super().__init__()
        self.context = context

    def visit_field(self, node: ast.Field) -> None:
        # Only select queries matter here; the default would walk every field's type graph.
        pass

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        super().visit_select_query(node)
        if node.select_from is None or not isinstance(node.select_from.table, ast.SelectQuery):
            return
        try:
            decline_reason = self._rewrite(node, node.select_from.table)
        except Exception as err:
            # Pure optimization: _rewrite mutates nothing until every check passes, so a raise leaves the query intact.
            logger.warning("events_subquery_pushdown_unexpected_error", error=str(err), exc_info=True)
            return
        if decline_reason is not None:
            logger.debug("events_subquery_pushdown_declined", reason=decline_reason)

    def _rewrite(self, outer: ast.SelectQuery, inner: ast.SelectQuery) -> str | None:
        """Apply both rewrites to an eligible outer select. Returns a decline reason, or None if applied."""
        assert outer.select_from is not None
        from_type = outer.select_from.type
        if not isinstance(from_type, ast.SelectQueryType | ast.SelectQueryAliasType):
            return "from_type_not_subquery"
        if outer.type is None or inner.type is None:
            return "untyped"
        if outer.select_from.sample is not None:
            return "outer_sample"
        if not self._joins_commute_with_left_filter(outer.select_from):
            return "outer_join_not_left_filter_safe"
        inner_reason = self._inner_decline_reason(inner)
        if inner_reason is not None:
            return inner_reason
        columns = _ExportedColumns(inner, from_type, self.context)
        if not columns:
            return "no_exported_events_columns"

        # An outer stream-dependent function sees a different input once the subquery filters earlier, so only the
        # key reads move then. Aggregates and windows are fine: a WHERE is applied before them either way.
        pushed: list[ast.Expr] = []
        residual_where = outer.where
        if not _depends_on_row_stream(_outer_expressions(outer), include_aggregates=False):
            pushed, residual_where = self._split_where(outer, columns)

        taken_names = set(outer.type.columns) | set(outer.type.aliases) | set(inner.type.columns)
        hoister = _KeyReadHoister(columns, taken_names)
        new_select = [cast(ast.Expr, hoister.visit(expr)) for expr in outer.select]
        new_where = cast(ast.Expr | None, hoister.visit(residual_where))
        new_prewhere = cast(ast.Expr | None, hoister.visit(outer.prewhere))
        new_having = cast(ast.Expr | None, hoister.visit(outer.having))
        new_qualify = cast(ast.Expr | None, hoister.visit(outer.qualify))
        new_group_by = [cast(ast.Expr, hoister.visit(expr)) for expr in outer.group_by] if outer.group_by else None
        new_order_by = [cast(ast.OrderExpr, hoister.visit(expr)) for expr in outer.order_by] if outer.order_by else None
        new_array_join_list = (
            [cast(ast.Expr, hoister.visit(expr)) for expr in outer.array_join_list] if outer.array_join_list else None
        )
        new_limit_by = cast(ast.LimitByExpr | None, hoister.visit(outer.limit_by))
        new_window_exprs = (
            {name: cast(ast.WindowExpr, hoister.visit(expr)) for name, expr in outer.window_exprs.items()}
            if outer.window_exprs
            else None
        )
        rewritten_join_constraints: list[tuple[ast.JoinExpr, ast.Expr]] = []
        join = outer.select_from.next_join
        while join is not None:
            if join.constraint is not None:
                rewritten_join_constraints.append((join, cast(ast.Expr, hoister.visit(join.constraint.expr))))
            join = join.next_join

        if not pushed and not hoister.added:
            return "nothing_to_move"

        # Commit.
        if pushed:
            inner.where = _and([*(_conjuncts(inner.where) if inner.where is not None else []), *pushed])
        for column in hoister.added.values():
            inner.select.append(column)
            inner.type.columns[column.alias] = column.type or ast.UnknownType()
        for alias_type, new_type in hoister.alias_type_updates:
            alias_type.type = new_type
        outer.select = new_select
        outer.where = new_where
        outer.prewhere = new_prewhere
        outer.having = new_having
        outer.qualify = new_qualify
        outer.group_by = new_group_by
        outer.order_by = new_order_by
        outer.array_join_list = new_array_join_list
        outer.limit_by = new_limit_by
        outer.window_exprs = new_window_exprs
        for join_expr, constraint_expr in rewritten_join_constraints:
            assert join_expr.constraint is not None
            join_expr.constraint.expr = constraint_expr
        return None

    def _joins_commute_with_left_filter(self, select_from: ast.JoinExpr) -> bool:
        join = select_from.next_join
        while join is not None:
            if join.join_type is None or join.join_type.removeprefix("GLOBAL ") not in _LEFT_FILTER_SAFE_JOIN_TYPES:
                return False
            join = join.next_join
        return True

    def _inner_decline_reason(self, inner: ast.SelectQuery) -> str | None:
        """None when the subquery is a pure row filter over the events table, else why it is not."""
        if inner.select_from is None or not isinstance(inner.select_from.table, ast.Field):
            return "inner_from_not_table"
        if not _is_events_table(inner.select_from.type):
            return "inner_from_not_events"
        if inner.select_from.next_join is not None:
            return "inner_has_join"
        if inner.select_from.sample is not None:
            return "inner_sample"
        if inner.ctes:
            return "inner_ctes"
        if (
            inner.distinct
            or inner.group_by
            or inner.group_by_mode is not None
            or inner.having is not None
            or inner.qualify is not None
            or inner.window_exprs
            or inner.array_join_list
            or inner.limit is not None
            or inner.offset is not None
            or inner.limit_by is not None
        ):
            return "inner_not_row_filter"
        if _depends_on_row_stream([*inner.select, *(inner.order_by or [])], include_aggregates=True):
            return "inner_depends_on_row_stream"
        return None

    def _split_where(self, outer: ast.SelectQuery, columns: _ExportedColumns) -> tuple[list[ast.Expr], ast.Expr | None]:
        """The conjuncts of the outer WHERE rewritten for the subquery, and the residual outer WHERE."""
        if outer.where is None:
            return [], None
        visible_aliases = {
            expr.alias: expr.expr for expr in outer.select if isinstance(expr, ast.Alias) and not expr.hidden
        }
        pushed: list[ast.Expr] = []
        kept: list[ast.Expr] = []
        for conjunct in _conjuncts(outer.where):
            moved = self._movable(conjunct, columns, visible_aliases)
            if moved is None:
                kept.append(conjunct)
            else:
                pushed.append(moved)
        return pushed, _and(kept)

    def _movable(
        self, conjunct: ast.Expr, columns: _ExportedColumns, visible_aliases: dict[str, ast.Expr]
    ) -> ast.Expr | None:
        """The conjunct rewritten to read the events table, or None when it must stay in the outer query."""
        inlined = SelectAliasInliner(visible_aliases).visit(conjunct)
        # Checked after alias inlining, because the alias body can hide them. An arrayJoin would multiply rows in a
        # different scope from the outer copy; an unresolved IN COHORT becomes a join after this pass.
        if contains_row_multiplying_function(inlined) or contains_in_cohort(inlined):
            return None
        rewriter = _ConjunctRewriter(columns)
        rewritten = cast(ast.Expr, rewriter.visit(inlined))
        if rewriter.blocked or rewriter.moved == 0:
            return None
        return rewritten
