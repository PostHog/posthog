from typing import List

from posthog.hogql import ast
from posthog.hogql.errors import HogQLException
from posthog.hogql.visitor import TraversingVisitor


def expand_asterisks(node: ast.Expr):
    AsteriskExpander().visit(node)


class AsteriskExpander(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery):
        super().visit_select_query(node)

        columns: List[ast.Expr] = []
        for column in node.select:
            if isinstance(column.type, ast.AsteriskType):
                asterisk = column.type
                if isinstance(asterisk.table, ast.TableType) or isinstance(asterisk.table, ast.TableAliasType):
                    table = asterisk.table
                    while isinstance(table, ast.TableAliasType):
                        table = table.table_type
                    if isinstance(table, ast.TableType):
                        database_fields = table.table.get_asterisk()
                        for key in database_fields.keys():
                            type = ast.FieldType(name=key, table=asterisk.table)
                            columns.append(ast.Field(chain=[key], type=type))
                            node.type.columns[key] = type
                    else:
                        raise HogQLException("Can't expand asterisk (*) on table")
                elif isinstance(asterisk.table, ast.SelectQueryType) or isinstance(
                    asterisk.table, ast.SelectQueryAliasType
                ):
                    select = asterisk.table
                    while isinstance(select, ast.SelectQueryAliasType):
                        select = select.type
                    if isinstance(select, ast.SelectQueryType):
                        for name in select.columns.keys():
                            type = ast.FieldType(name=name, table=asterisk.table)
                            columns.append(ast.Field(chain=[name], type=type))
                            node.type.columns[name] = type
                    else:
                        raise HogQLException("Can't expand asterisk (*) on subquery")
                else:
                    raise HogQLException(f"Can't expand asterisk (*) on a type of type {type(asterisk.table).__name__}")

            else:
                columns.append(column)
        node.select = columns
