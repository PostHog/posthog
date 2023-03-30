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
            if isinstance(column.ref, ast.AsteriskRef):
                asterisk = column.ref
                if isinstance(asterisk.table, ast.BaseTableRef):
                    table = asterisk.table.resolve_database_table()
                    database_fields = table.get_asterisk()
                    for key, field_type in database_fields.items():
                        # TODO: make this bulletproof
                        if isinstance(field_type, ast.FieldTraverser) and len(field_type.chain) == 2:
                            chain = field_type.chain
                            ref = ast.PropertyRef(
                                name=chain[1], parent=ast.FieldRef(name=chain[0], table=asterisk.table)
                            )
                            columns.append(ast.Field(chain=[key], ref=ref))
                            node.ref.columns[key] = ref
                        else:
                            ref = ast.FieldRef(name=key, table=asterisk.table)
                            columns.append(ast.Field(chain=[key], ref=ref))
                            node.ref.columns[key] = ref
                elif (
                    isinstance(asterisk.table, ast.SelectUnionQueryRef)
                    or isinstance(asterisk.table, ast.SelectQueryRef)
                    or isinstance(asterisk.table, ast.SelectQueryAliasRef)
                ):
                    select = asterisk.table
                    while isinstance(select, ast.SelectQueryAliasRef):
                        select = select.ref
                    if isinstance(select, ast.SelectUnionQueryRef):
                        select = select.refs[0]
                    if isinstance(select, ast.SelectQueryRef):
                        for name in select.columns.keys():
                            ref = ast.FieldRef(name=name, table=asterisk.table)
                            columns.append(ast.Field(chain=[name], ref=ref))
                            node.ref.columns[name] = ref
                    else:
                        raise ValueError("Can't expand asterisk (*) on subquery")
                else:
                    raise ValueError(f"Can't expand asterisk (*) on a ref of type {type(asterisk.table).__name__}")

            else:
                columns.append(column)
        node.select = columns
