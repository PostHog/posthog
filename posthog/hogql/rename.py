from dataclasses import replace

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor


class _TableReferenceSpans(TraversingVisitor):
    def __init__(self, table_name: str) -> None:
        self.table_name = table_name
        self.spans: set[tuple[int, int]] = set()
        self.cte_names: list[set[str]] = []

    def _record(self, table: ast.Expr | None) -> None:
        if not isinstance(table, ast.Field) or ".".join(map(str, table.chain)) != self.table_name:
            return
        if self.cte_names and self.table_name in self.cte_names[-1]:
            return
        if table.start is None or table.end is None:
            raise ValueError("Cannot safely rewrite a table reference without source positions")
        self.spans.add((table.start, table.end))

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        self._record(node.table)
        super().visit_join_expr(node)

    def visit_pivot_expr(self, node: ast.PivotExpr) -> None:
        self._record(node.table)
        super().visit_pivot_expr(node)

    def visit_unpivot_expr(self, node: ast.UnpivotExpr) -> None:
        self._record(node.table)
        super().visit_unpivot_expr(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        inherited_names = self.cte_names[-1] if self.cte_names else set()
        cte_names = set(inherited_names)
        for name, cte in (node.ctes or {}).items():
            self.cte_names.append(set(cte_names))
            try:
                self.visit(cte)
            finally:
                self.cte_names.pop()
            cte_names.add(name)

        self.cte_names.append(cte_names)
        try:
            super().visit_select_query(replace(node, ctes=None))
        finally:
            self.cte_names.pop()


def rewrite_table_references(sql: str, old_name: str, new_name: str) -> tuple[str, int]:
    """Rewrite exact HogQL table sources and leave other SQL text unchanged."""
    query = parse_select(sql)
    visitor = _TableReferenceSpans(old_name)
    visitor.visit(query)

    rewritten = sql
    for start, end in sorted(visitor.spans, reverse=True):
        if start < 0 or end > len(sql) or start >= end:
            raise ValueError("Cannot safely rewrite a table reference with invalid source positions")
        rewritten = rewritten[:start] + new_name + rewritten[end:]

    return rewritten, len(visitor.spans)
