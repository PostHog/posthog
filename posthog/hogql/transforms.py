from typing import List

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor


def expand_splashes(node: ast.Expr):
    SplashExpander().visit(node)


class SplashExpander(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery):
        columns: List[ast.Expr] = []
        for column in node.select:
            if isinstance(column.symbol, ast.SplashSymbol):
                splash = column.symbol
                table = splash.table
                while isinstance(table, ast.TableAliasSymbol):
                    table = table.table
                if isinstance(table, ast.TableSymbol):
                    database_fields = table.table.get_splash()
                    for key in database_fields.keys():
                        columns.append(ast.Field(chain=[key], symbol=ast.FieldSymbol(name=key, table=splash.table)))
                else:
                    raise ValueError("Can't expand splash (*) on subquery")
            else:
                columns.append(column)
        node.select = columns
