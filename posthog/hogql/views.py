from posthog.hogql import ast
from typing import List, Optional, Literal
from posthog.hogql.context import HogQLContext

from posthog.hogql.database.models import (
    SavedQuery,
)

from posthog.hogql.visitor import CloningVisitor
from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.property_types import resolve_property_types


def resolve_views(
    node: ast.Expr,
    context: HogQLContext,
    dialect: Literal["hogql", "clickhouse"],
    scopes: Optional[List[ast.SelectQueryType]] = None,
) -> ast.Expr:
    return ViewResolver(scopes=scopes, context=context, dialect=dialect).visit(node)


class ViewResolver(CloningVisitor):
    """The ViewResolver only visits an AST and resolves all views"""

    def __init__(
        self,
        context: HogQLContext,
        dialect: Literal["hogql", "clickhouse"] = "clickhouse",
        scopes: Optional[List[ast.SelectQueryType]] = None,
    ):
        super().__init__()
        # Each SELECT query creates a new scope (type). Store all of them in a list as we traverse the tree.
        self.scopes: List[ast.SelectQueryType] = scopes or []
        self.current_view_depth: int = 0
        self.context = context
        self.dialect = dialect
        self.database = context.database

    def visit_join_expr(self, node: ast.JoinExpr):
        from posthog.hogql.resolver import resolve_types

        if (
            isinstance(node.type, ast.TableAliasType)
            and isinstance(node.type.table_type, ast.TableType)
            and isinstance(node.type.table_type.table, SavedQuery)
        ):
            resolved_table = parse_select(str(node.type.table_type.table.query))
            resolved_table = resolve_types(resolved_table, self.context, self.dialect)
            resolved_table = resolve_property_types(resolved_table, self.context)

            node.type = ast.SelectQueryAliasType(
                select_query_type=resolved_table.type,
                alias=node.alias,
            )
            node.table = resolved_table

        return node
