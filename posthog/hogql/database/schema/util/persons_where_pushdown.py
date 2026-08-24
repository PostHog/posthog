"""Fold a `persons` query's outer WHERE into the argMax subquery that reads the raw person rows.

The `persons` lazy table expands into `argMax(...) FROM raw_persons WHERE id IN (<candidate ids>) GROUP BY id`,
and the caller's WHERE stays outside to re-check the filter against the deduplicated values. A filter that
holds an `IN (subquery)` arm therefore runs that subquery twice: once to build the candidate ids, once to
re-check them. ClickHouse builds one set per subquery occurrence and only shares sets inside a single query
scope, so the two occurrences each scan the whole source table.

This module rewrites the pair into one scope: the `IN (subquery)` arms move into the argMax select's own
WHERE, and the exact outer filter becomes its HAVING. Both then reference the same set, so it is built once.

Only arms of the form `persons.id IN (subquery)` move. Their truth depends on the person id alone, never on
which version of the person row is read, so filtering rows by them before the GROUP BY keeps every version
of every candidate person and leaves argMax reading the latest one.
"""

from typing import Literal, Optional, cast

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import LazyTable, LazyTableToAdd
from posthog.hogql.database.schema.util.where_clause_extractor import WhereClauseExtractor
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.dataclasses import frozen


@frozen
class SinglePassFilter:
    """Where the caller's filter goes once it is folded into the argMax select."""

    candidate: ast.Expr
    """Predicate on the raw person rows: which ids to aggregate."""

    recheck: ast.Expr
    """The caller's filter, re-pointed at the subquery's own columns, to apply after the aggregation."""


def plan_single_pass_filter(
    node: ast.SelectQuery,
    join_or_table: LazyTableToAdd,
    context: HogQLContext,
) -> Optional[SinglePassFilter]:
    """Plan the fold for `node`'s WHERE, or return None to keep the two-level filter."""
    where = node.where
    if where is None or node.prewhere is not None:
        return None
    if node.select_from is None or node.select_from.next_join is not None:
        return None

    lazy_table = join_or_table.lazy_table
    fields_accessed = join_or_table.fields_accessed

    combinator, operands = _split_boolean(where)
    hoistable = [
        cast(ast.CompareOperation, operand)
        for operand in operands
        if _is_id_in_subquery(operand, lazy_table, fields_accessed)
    ]
    if not hoistable:
        return None
    if not _every_field_maps_to_subquery(where, lazy_table, fields_accessed):
        return None

    hoisted_ids = {id(operand) for operand in hoistable}
    rest = [operand for operand in operands if id(operand) not in hoisted_ids]
    if combinator == "and":
        # The raw person rows are read team-scoped anyway, so a team conjunct needs no pre-filter of its own.
        rest = [operand for operand in rest if not _is_team_scope(operand, lazy_table, fields_accessed)]

    candidate_parts: list[ast.Expr] = []
    if rest:
        if combinator == "and":
            # An `IN (subquery)` conjunct usually prunes the pre-filter's own scan by primary key, so pulling it
            # out of there costs more than the second pass does. Leave the two-level filter alone.
            return None
        rest_expr = rest[0] if len(rest) == 1 else _combine(combinator, rest)
        extractor = WhereClauseExtractor(context)
        extractor.add_local_tables(join_or_table)
        inner_where = extractor.get_inner_where(
            ast.SelectQuery(select=[], select_from=node.select_from, where=rest_expr)
        )
        if inner_where is None:
            # Without a pre-filter for the remaining arms the candidate set would be every person.
            return None
        prefilter = parse_select("SELECT id FROM raw_persons AS where_optimization")
        assert isinstance(prefilter, ast.SelectQuery)
        prefilter.where = inner_where
        candidate_parts.append(
            ast.CompareOperation(op=ast.CompareOperationOp.In, left=ast.Field(chain=["id"]), right=prefilter)
        )

    for arm in hoistable:
        candidate_parts.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["id"]),
                right=clone_expr(arm.right, clear_types=True, clear_locations=True),
            )
        )

    return SinglePassFilter(
        candidate=candidate_parts[0] if len(candidate_parts) == 1 else _combine(combinator, candidate_parts),
        recheck=_SubqueryAliasRewriter(lazy_table, fields_accessed).visit(where),
    )


def _split_boolean(expr: ast.Expr) -> tuple[Literal["and", "or"], list[ast.Expr]]:
    """Break a boolean root into its operands, flattening nested operands of the same kind.

    A single predicate reads as a one-operand AND.
    """
    combinator = _boolean_kind(expr)
    if combinator is None:
        return "and", [expr]

    operands: list[ast.Expr] = []
    queue = list(_boolean_operands(expr))
    while queue:
        operand = queue.pop(0)
        if _boolean_kind(operand) == combinator:
            queue = [*_boolean_operands(operand), *queue]
        else:
            operands.append(operand)
    return combinator, operands


def _boolean_kind(expr: ast.Expr) -> Optional[Literal["and", "or"]]:
    if isinstance(expr, ast.And):
        return "and"
    if isinstance(expr, ast.Or):
        return "or"
    if isinstance(expr, ast.Call) and expr.name in ("and", "or"):
        return "and" if expr.name == "and" else "or"
    return None


def _boolean_operands(expr: ast.Expr) -> list[ast.Expr]:
    if isinstance(expr, ast.And | ast.Or):
        return expr.exprs
    return cast(ast.Call, expr).args


def _combine(combinator: Literal["and", "or"], exprs: list[ast.Expr]) -> ast.Expr:
    return ast.And(exprs=exprs) if combinator == "and" else ast.Or(exprs=exprs)


def _is_id_in_subquery(expr: ast.Expr, lazy_table: LazyTable, fields_accessed: dict[str, list[str | int]]) -> bool:
    return (
        isinstance(expr, ast.CompareOperation)
        and expr.op == ast.CompareOperationOp.In
        and isinstance(expr.right, ast.SelectQuery | ast.SelectSetQuery)
        and _subquery_alias(expr.left, lazy_table, fields_accessed) == "id"
    )


def _is_team_scope(expr: ast.Expr, lazy_table: LazyTable, fields_accessed: dict[str, list[str | int]]) -> bool:
    return (
        isinstance(expr, ast.CompareOperation)
        and expr.op == ast.CompareOperationOp.Eq
        and isinstance(expr.right, ast.Constant)
        and _subquery_alias(expr.left, lazy_table, fields_accessed) == "team_id"
    )


def _subquery_alias(
    expr: ast.Expr, lazy_table: LazyTable, fields_accessed: dict[str, list[str | int]]
) -> Optional[str]:
    """Alias under which the argMax subquery exposes this reference to a persons column, if it does."""
    while isinstance(expr, ast.Alias):
        # The resolver wraps field references in hidden aliases.
        expr = expr.expr
    if not isinstance(expr, ast.Field):
        return None

    field_type = expr.type
    while isinstance(field_type, ast.FieldAliasType):
        field_type = field_type.type

    if isinstance(field_type, ast.PropertyType):
        alias = field_type.joined_subquery_field_name
        base_type = field_type.field_type
    elif isinstance(field_type, ast.FieldType):
        alias = field_type.name
        base_type = field_type
    else:
        return None

    if alias is None or alias not in fields_accessed:
        return None

    table_type = base_type.table_type
    while isinstance(table_type, ast.VirtualTableType):
        table_type = table_type.table_type
    if not isinstance(table_type, ast.LazyTableType) or table_type.table is not lazy_table:
        return None

    return alias


class _SubqueryAliasRewriter(CloningVisitor):
    """Re-point references to persons columns at the aliases of the argMax subquery they came from."""

    def __init__(self, lazy_table: LazyTable, fields_accessed: dict[str, list[str | int]]) -> None:
        super().__init__(clear_types=True, clear_locations=True)
        self.lazy_table = lazy_table
        self.fields_accessed = fields_accessed

    def visit_field(self, node: ast.Field) -> ast.Expr:
        alias = _subquery_alias(node, self.lazy_table, self.fields_accessed)
        if alias is not None:
            return ast.Field(chain=[alias])
        return super().visit_field(node)

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        # A subquery resolves its own columns, so leave everything inside it alone.
        return clone_expr(node, clear_types=True, clear_locations=True)


class _UnmappedFieldFinder(TraversingVisitor):
    """Find references the argMax subquery cannot serve, which make the filter unsafe to fold in."""

    def __init__(self, lazy_table: LazyTable, fields_accessed: dict[str, list[str | int]]) -> None:
        super().__init__()
        self.lazy_table = lazy_table
        self.fields_accessed = fields_accessed
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        if _subquery_alias(node, self.lazy_table, self.fields_accessed) is None:
            self.found = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        pass

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass


def _every_field_maps_to_subquery(
    where: ast.Expr, lazy_table: LazyTable, fields_accessed: dict[str, list[str | int]]
) -> bool:
    finder = _UnmappedFieldFinder(lazy_table, fields_accessed)
    finder.visit(where)
    return not finder.found
