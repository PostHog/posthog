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
                if isinstance(asterisk.table, ast.TableSymbol) or isinstance(asterisk.table, ast.TableAliasSymbol):
                    table = asterisk.table
                    while isinstance(table, ast.TableAliasSymbol):
                        table = table.table
                    if isinstance(table, ast.TableSymbol):
                        database_fields = table.table.get_asterisk()
                        for key in database_fields.keys():
                            columns.append(
                                ast.Field(chain=[key], symbol=ast.FieldSymbol(name=key, table=asterisk.table))
                            )
                    else:
                        raise ValueError("Can't expand asterisk (*) on table")
                elif isinstance(asterisk.table, ast.SelectQuerySymbol) or isinstance(
                    asterisk.table, ast.SelectQueryAliasSymbol
                ):
                    select = asterisk.table
                    while isinstance(select, ast.SelectQueryAliasSymbol):
                        select = select.symbol
                    if isinstance(select, ast.SelectQuerySymbol):
                        for name in select.columns.keys():
                            columns.append(
                                ast.Field(chain=[name], symbol=ast.FieldSymbol(name=name, table=asterisk.table))
                            )
                    else:
                        raise ValueError("Can't expand asterisk (*) on subquery")
                else:
                    raise ValueError(f"Can't expand asterisk (*) on a symbol of type {type(asterisk.table).__name__}")

            else:
                columns.append(column)
        node.select = columns
