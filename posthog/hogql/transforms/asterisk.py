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
            if isinstance(column.pointer, ast.AsteriskPointer):
                asterisk = column.pointer
                if isinstance(asterisk.table, ast.BaseTablePointer):
                    table = asterisk.table.resolve_database_table()
                    database_fields = table.get_asterisk()
                    for key in database_fields.keys():
                        pointer = ast.FieldPointer(name=key, table=asterisk.table)
                        columns.append(ast.Field(chain=[key], pointer=pointer))
                        node.pointer.columns[key] = pointer
                elif isinstance(asterisk.table, ast.SelectQueryPointer) or isinstance(
                    asterisk.table, ast.SelectQueryAliasPointer
                ):
                    select = asterisk.table
                    while isinstance(select, ast.SelectQueryAliasPointer):
                        select = select.pointer
                    if isinstance(select, ast.SelectQueryPointer):
                        for name in select.columns.keys():
                            pointer = ast.FieldPointer(name=name, table=asterisk.table)
                            columns.append(ast.Field(chain=[name], pointer=pointer))
                            node.pointer.columns[name] = pointer
                    else:
                        raise ValueError("Can't expand asterisk (*) on subquery")
                else:
                    raise ValueError(f"Can't expand asterisk (*) on a pointer of type {type(asterisk.table).__name__}")

            else:
                columns.append(column)
        node.select = columns
