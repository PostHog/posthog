from typing import List

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor


def expand_asterisks(node: ast.Expr):
    AsteriskExpander().visit(node)


class AsteriskExpander(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery):
        super().visit_select_query(node)

        columns: List[ast.Expr] = []
        for column in node.select:
            if isinstance(column.symbol, ast.AsteriskSymbol):
                asterisk = column.symbol
                if isinstance(asterisk.table, ast.BaseTableSymbol):
                    table = asterisk.table.resolve_database_table()
                    database_fields = table.get_asterisk()
                    for key in database_fields.keys():
                        symbol = ast.FieldSymbol(name=key, table=asterisk.table)
                        columns.append(ast.Field(chain=[key], symbol=symbol))
                        node.symbol.columns[key] = symbol
                elif isinstance(asterisk.table, ast.SelectQuerySymbol) or isinstance(
                    asterisk.table, ast.SelectQueryAliasSymbol
                ):
                    select = asterisk.table
                    while isinstance(select, ast.SelectQueryAliasSymbol):
                        select = select.symbol
                    if isinstance(select, ast.SelectQuerySymbol):
                        for name in select.columns.keys():
                            symbol = ast.FieldSymbol(name=name, table=asterisk.table)
                            columns.append(ast.Field(chain=[name], symbol=symbol))
                            node.symbol.columns[name] = symbol
                    else:
                        raise ValueError("Can't expand asterisk (*) on subquery")
                else:
                    raise ValueError(f"Can't expand asterisk (*) on a symbol of type {type(asterisk.table).__name__}")

            else:
                columns.append(column)
        node.select = columns
