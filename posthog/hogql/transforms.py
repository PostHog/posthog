from typing import List

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor


def expand_asterisks(node: ast.Expr):
    AsteriskExpander().visit(node)


class AsteriskExpander(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery):
        columns: List[ast.Expr] = []
        for column in node.select:
            if isinstance(column.symbol, ast.AsteriskSymbol):
                asterisk = column.symbol
                table = asterisk.table
                while isinstance(table, ast.TableAliasSymbol):
                    table = table.table
                if isinstance(table, ast.TableSymbol):
                    database_fields = table.table.get_asterisk()
                    for key in database_fields.keys():
                        columns.append(ast.Field(chain=[key], symbol=ast.FieldSymbol(name=key, table=asterisk.table)))
                else:
                    raise ValueError("Can't expand asterisk (*) on subquery")
            else:
                columns.append(column)
        node.select = columns
