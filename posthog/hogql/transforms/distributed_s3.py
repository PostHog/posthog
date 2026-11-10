from posthog.hogql import ast
from posthog.hogql.database.s3_table import DataWarehouseTable
from posthog.hogql.visitor import TraversingVisitor


class _WarehouseScanFinder(TraversingVisitor):
    def __init__(self, query: ast.SelectQuery | ast.SelectSetQuery) -> None:
        self.allowed_queries = {id(query)}
        self.eligible = True

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if id(node) not in self.allowed_queries or node.ctes or node.select_from is None:
            self.eligible = False
            return
        self.allowed_queries.remove(id(node))
        super().visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        if id(node) not in self.allowed_queries or any(
            part.set_operator != "UNION ALL" for part in node.subsequent_select_queries
        ):
            self.eligible = False
            return
        self.allowed_queries.remove(id(node))
        self.allowed_queries.update(id(query) for query in node.select_queries())
        super().visit_select_set_query(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if node.next_join or node.constraint or node.table_args:
            self.eligible = False
            return
        if isinstance(node.table, (ast.SelectQuery, ast.SelectSetQuery)):
            self.allowed_queries.add(id(node.table))
        elif isinstance(node.table, ast.Field):
            table_type = node.table.type
            if isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                table_type = table_type.table_type
            if not isinstance(table_type, ast.TableType) or not isinstance(table_type.table, DataWarehouseTable):
                self.eligible = False
                return
        else:
            self.eligible = False
            return
        super().visit_join_expr(node)

    def visit_field(self, node: ast.Field) -> None:
        # Resolved field types refer back to query scopes; only the SQL tree determines where a read executes.
        pass


def can_distribute_warehouse_query(query: ast.SelectQuery | ast.SelectSetQuery) -> bool:
    finder = _WarehouseScanFinder(query)
    finder.visit(query)
    return finder.eligible
