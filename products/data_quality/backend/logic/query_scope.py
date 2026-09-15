from dataclasses import replace

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from .errors import CheckConfigError


class ScopedQueryVisitor(TraversingVisitor):
    def __init__(self) -> None:
        self.cte_names: set[str] = set()

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        parent_ctes = self.cte_names
        self.cte_names = set(parent_ctes)
        try:
            for cte in (node.ctes or {}).values():
                self.visit(cte)
            super().visit_select_query(replace(node, ctes=None))
        finally:
            self.cte_names = parent_ctes

    def visit_cte(self, node: ast.CTE) -> None:
        if node.recursive and isinstance(node.expr, ast.SelectSetQuery):
            self.visit(node.expr.initial_select_query)
            self.cte_names.add(node.name)
        self.visit(node.expr)
        self.cte_names.add(node.name)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        parent_ctes = self.cte_names
        self.cte_names = set(parent_ctes)
        try:
            self.visit(node.initial_select_query)
            if isinstance(node.initial_select_query, ast.SelectQuery):
                self.cte_names.update(node.initial_select_query.ctes or {})
            for branch in node.subsequent_select_queries:
                self.visit(branch.select_query)
            self.visit(node.limit)
            self.visit(node.offset)
        finally:
            self.cte_names = parent_ctes


class _TableReferences(ScopedQueryVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.table_names: set[str] = set()

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if node.table_args is not None or not isinstance(node.table, ast.Field | ast.SelectQuery | ast.SelectSetQuery):
            raise CheckConfigError(
                "Custom SQL checks cannot use this table expression. Use a table name or a SELECT subquery."
            )
        if isinstance(node.table, ast.Field):
            name = ".".join(str(part) for part in node.table.chain)
            if name not in self.cte_names:
                self.table_names.add(name)
        super().visit_join_expr(node)


def referenced_table_names(query: ast.SelectQuery | ast.SelectSetQuery) -> list[str]:
    references = _TableReferences()
    references.visit(query)
    return sorted(references.table_names)
