from collections.abc import Callable
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor


class FieldReferenceRewriter(CloningVisitor):
    def __init__(self, outer_table_alias: str, inner_table_name: str):
        super().__init__(clear_locations=True)
        self.outer_table_alias = outer_table_alias
        self.inner_table_name = inner_table_name

    def visit_field(self, node: ast.Field):
        if len(node.chain) >= 2 and node.chain[0] == self.outer_table_alias:
            return ast.Field(chain=[self.inner_table_name, *node.chain[1:]])
        elif len(node.chain) == 1:
            return ast.Field(chain=[self.inner_table_name, node.chain[0]])
        return ast.Field(chain=list(node.chain))


def unwrap_alias(node: ast.Expr) -> ast.Expr:
    if isinstance(node, ast.Alias):
        return unwrap_alias(node.expr)
    return node


def resolve_order_by_alias(order_expr: ast.OrderExpr, outer_query: ast.SelectQuery) -> Optional[ast.Expr]:
    expr = unwrap_alias(order_expr.expr)
    if not isinstance(expr, ast.Field) or len(expr.chain) != 1 or not outer_query.select:
        return None
    alias_name = expr.chain[0]
    for select_expr in outer_query.select:
        if isinstance(select_expr, ast.Alias) and select_expr.alias == alias_name:
            return select_expr.expr
    return None


def push_down_order_by(
    outer_query: ast.SelectQuery,
    inner_query: ast.SelectQuery,
    outer_table_alias: str,
    inner_table_name: str,
    should_push_down: Callable[[ast.OrderExpr, ast.SelectQuery], bool],
) -> None:
    if not outer_query or not outer_query.order_by or not outer_query.limit:
        return

    rewriter = FieldReferenceRewriter(outer_table_alias, inner_table_name)
    pushed_order_by = [
        ast.OrderExpr(
            expr=rewriter.visit(resolve_order_by_alias(o, outer_query) or o.expr),
            order=o.order,
        )
        for o in outer_query.order_by
        if should_push_down(o, outer_query)
    ]

    if not pushed_order_by:
        return

    if inner_query.order_by:
        inner_query.order_by = pushed_order_by + list(inner_query.order_by)
    else:
        inner_query.order_by = pushed_order_by

    inner_query.limit = CloningVisitor(clear_locations=True).visit(outer_query.limit)
