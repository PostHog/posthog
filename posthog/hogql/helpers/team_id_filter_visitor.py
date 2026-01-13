from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor


@dataclass(frozen=True)
class TeamIdFilterTables:
    with_team_id: set[str]
    without_team_id: set[str]


@dataclass
class _SelectScope:
    table_identifiers: dict[str, str]
    table_names: set[str]

    @classmethod
    def from_join_expr(cls, join_expr: Optional[ast.JoinExpr]) -> _SelectScope:
        table_identifiers: dict[str, str] = {}
        table_names: set[str] = set()
        current = join_expr

        while current:
            if isinstance(current.table, ast.Field):
                table_name = ".".join(str(part) for part in current.table.chain)
                identifier = current.alias or table_name
                table_identifiers[identifier] = table_name
                table_names.add(table_name)
            current = current.next_join

        return cls(table_identifiers=table_identifiers, table_names=table_names)


class TeamIdFilterVisitor(TraversingVisitor):
    def __init__(self) -> None:
        self.tables_with_team_id: set[str] = set()
        self.tables_seen: set[str] = set()
        self._scope_stack: list[_SelectScope] = []

    @property
    def tables_without_team_id(self) -> set[str]:
        return self.tables_seen - self.tables_with_team_id

    def visit_select_query(self, node: ast.SelectQuery):
        scope = _SelectScope.from_join_expr(node.select_from)
        self._scope_stack.append(scope)
        self.tables_seen.update(scope.table_names)
        super().visit_select_query(node)
        self._scope_stack.pop()

    def visit_compare_operation(self, node: ast.CompareOperation):
        if node.op == ast.CompareOperationOp.Eq:
            self._mark_team_id_filter(node.left)
            self._mark_team_id_filter(node.right)
        super().visit_compare_operation(node)

    def visit_call(self, node: ast.Call):
        if node.name == "equals" and len(node.args) == 2:
            self._mark_team_id_filter(node.args[0])
            self._mark_team_id_filter(node.args[1])
        super().visit_call(node)

    def _mark_team_id_filter(self, expr: ast.Expr) -> None:
        if not isinstance(expr, ast.Field):
            return
        if not expr.chain or str(expr.chain[-1]) != "team_id":
            return

        table_name = self._resolve_table_name(expr)
        if table_name:
            self.tables_with_team_id.add(table_name)

    def _resolve_table_name(self, field: ast.Field) -> Optional[str]:
        if not self._scope_stack:
            return None

        scope = self._scope_stack[-1]
        if len(field.chain) >= 2 and str(field.chain[-1]) == "team_id":
            identifier = str(field.chain[-2])
            return scope.table_identifiers.get(identifier) or ".".join(str(part) for part in field.chain[:-1])

        if len(field.chain) == 1 and str(field.chain[0]) == "team_id":
            if len(scope.table_names) == 1:
                return next(iter(scope.table_names))
        return None


def list_team_id_filters(select_query: ast.SelectQuery | ast.SelectSetQuery) -> TeamIdFilterTables:
    visitor = TeamIdFilterVisitor()
    visitor.visit(select_query)
    return TeamIdFilterTables(
        with_team_id=visitor.tables_with_team_id,
        without_team_id=visitor.tables_without_team_id,
    )
