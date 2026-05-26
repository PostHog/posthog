from collections.abc import Callable
from typing import TYPE_CHECKING, Optional

from posthog.hogql import ast
from posthog.hogql.ast import SelectQuery
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

if TYPE_CHECKING:
    from posthog.hogql.database.models import LazyTable


def argmax_select(
    table_name: str,
    select_fields: dict[str, list[str | int]],
    group_fields: list[str],
    argmax_field: str,
    deleted_field: Optional[str] = None,
    timestamp_field_to_clamp: Optional[str] = None,
) -> "SelectQuery":
    """
    Note: ClickHouse argmax will try to return the closest non null value which means
    if the value corresponding to the highest argmax is null, it won't be returned
    This select alters that to return the maximum argmax value even if null

    ┌─a────┬────b─┐
    │ a    │    1 │
    │ b    │    2 │
    │ c    │    2 │
    │ ᴺᵁᴸᴸ │    3 │
    │ ᴺᵁᴸᴸ │ ᴺᵁᴸᴸ │
    │ d    │ ᴺᵁᴸᴸ │
    └──────┴──────┘

    SELECT argMax(a, b), max(b) FROM test;

    ┌─argMax(a, b)─┬─max(b)─┐
    │ b            │      3 │ -- argMax = 'b' because it the first not Null value, max(b) is from another row!
    └──────────────┴────────┘

    see more: https://clickhouse.com/docs/sql-reference/aggregate-functions/reference/argmax

    we use tuple to force nulls to be treated as values and tupleElement select it after the call
    """
    argmax_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="tupleElement",
        args=[
            ast.Call(
                name="argMax", args=[ast.Call(name="tuple", args=[field]), ast.Field(chain=[table_name, argmax_field])]
            ),
            ast.Constant(value=1),
        ],
    )

    fields_to_group: list[ast.Expr] = []
    fields_to_select: list[ast.Expr] = []
    for name, chain in select_fields.items():
        if name not in group_fields:
            fields_to_select.append(
                ast.Alias(
                    alias=name,
                    expr=argmax_version(ast.Field(chain=[table_name, *chain])),
                )
            )
    for key in group_fields:
        fields_to_group.append(ast.Field(chain=[table_name, key]))
        fields_to_select.append(ast.Alias(alias=key, expr=ast.Field(chain=[table_name, key])))

    select_query = ast.SelectQuery(
        select=fields_to_select,
        select_from=ast.JoinExpr(table=ast.Field(chain=[table_name])),
        group_by=fields_to_group,
    )
    if deleted_field:
        select_query.having = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=argmax_version(ast.Field(chain=[table_name, deleted_field])),
            right=ast.Constant(value=0),
        )
    if timestamp_field_to_clamp:
        clause = ast.CompareOperation(
            op=ast.CompareOperationOp.Lt,
            left=argmax_version(ast.Field(chain=[table_name, timestamp_field_to_clamp])),
            right=parse_expr("now() + interval 1 day"),
        )
        select_query.having = clause if select_query.having is None else ast.And(exprs=[select_query.having, clause])

    return select_query


def _flatten_and(expr: ast.Expr) -> list[ast.Expr]:
    if isinstance(expr, ast.And):
        result: list[ast.Expr] = []
        for child in expr.exprs:
            result.extend(_flatten_and(child))
        return result
    return [expr]


def _unwrap_table_type(table_type: ast.Type) -> ast.Type:
    while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
        table_type = table_type.table_type
    return table_type


class _PushdownChecker(TraversingVisitor):
    """Walks an expression and stays True only if every Field reference resolves to
    `lazy_table` and uses a field name in `allowed_field_names`. Function calls,
    constants, and comparison operators are fine; subqueries and lambdas are not.
    """

    def __init__(self, lazy_table: "LazyTable", allowed_field_names: set[str]) -> None:
        super().__init__()
        self.lazy_table = lazy_table
        self.allowed_field_names = allowed_field_names
        self.is_pushable: bool = True
        self.has_field_ref: bool = False

    def visit_field(self, node: ast.Field) -> None:
        if not self.is_pushable:
            return
        if not isinstance(node.type, ast.FieldType):
            self.is_pushable = False
            return
        table_type = _unwrap_table_type(node.type.table_type)
        if not isinstance(table_type, ast.LazyTableType) or table_type.table is not self.lazy_table:
            self.is_pushable = False
            return
        if node.type.name not in self.allowed_field_names:
            self.is_pushable = False
            return
        self.has_field_ref = True

    def visit_lambda(self, node: ast.Lambda) -> None:
        self.is_pushable = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.is_pushable = False

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.is_pushable = False


class _PushdownCloner(CloningVisitor):
    """Clones an expression with types cleared, replacing Field nodes whose original
    type points to `lazy_table` with an unqualified `ast.Field(chain=[field_name])`.
    The inner subquery's SELECT exposes each group_field by the same alias, so the
    unqualified chain re-resolves there during `resolve_types`.
    """

    def __init__(self, lazy_table: "LazyTable") -> None:
        super().__init__(clear_types=True, clear_locations=True)
        self.lazy_table = lazy_table

    def visit_field(self, node: ast.Field) -> ast.Field:
        if isinstance(node.type, ast.FieldType):
            table_type = _unwrap_table_type(node.type.table_type)
            if isinstance(table_type, ast.LazyTableType) and table_type.table is self.lazy_table:
                return ast.Field(chain=[node.type.name])
        return super().visit_field(node)


def pushdown_predicates_to_argmax_subquery(
    subquery: ast.SelectQuery,
    outer_where: ast.Expr | None,
    lazy_table: "LazyTable",
    pushdown_field_names: set[str],
) -> None:
    """Push conjuncts from the outer WHERE into `subquery.where` when they reference
    only `pushdown_field_names` of `lazy_table`. The outer WHERE is left untouched
    because pushing without removing is always safe: the outer filter is redundant
    once the inner subquery has already applied it.

    `pushdown_field_names` must be a subset of the argmax subquery's GROUP BY keys,
    otherwise the filter would change result rows (the alias would point through an
    argMax aggregate). Callers are responsible for that invariant.
    """
    if outer_where is None or not pushdown_field_names:
        return
    pushable: list[ast.Expr] = []
    for conj in _flatten_and(outer_where):
        checker = _PushdownChecker(lazy_table, pushdown_field_names)
        checker.visit(conj)
        if checker.is_pushable and checker.has_field_ref:
            pushable.append(_PushdownCloner(lazy_table).visit(conj))
    if not pushable:
        return
    combined: ast.Expr = pushable[0] if len(pushable) == 1 else ast.And(exprs=pushable)
    subquery.where = combined if subquery.where is None else ast.And(exprs=[subquery.where, combined])
