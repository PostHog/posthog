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
        self._collect_team_id_filters(node)
        super().visit_select_query(node)
        self._scope_stack.pop()

    def _collect_team_id_filters(self, node: ast.SelectQuery) -> None:
        filter_exprs = [node.where, node.prewhere, node.having]
        for expr in filter_exprs:
            if expr is not None:
                self.tables_with_team_id.update(self._team_id_tables_from_expr(expr))

        join_expr = node.select_from
        while join_expr:
            if join_expr.constraint and join_expr.constraint.constraint_type == "ON":
                self.tables_with_team_id.update(self._team_id_tables_from_expr(join_expr.constraint.expr))
            join_expr = join_expr.next_join

    def _team_id_tables_from_expr(self, expr: ast.Expr) -> set[str]:
        if isinstance(expr, ast.And):
            and_tables: set[str] = set()
            for sub_expr in expr.exprs:
                and_tables.update(self._team_id_tables_from_expr(sub_expr))
            return and_tables

        if isinstance(expr, ast.Or):
            or_tables: Optional[set[str]] = None
            for sub_expr in expr.exprs:
                sub_tables = self._team_id_tables_from_expr(sub_expr)
                if or_tables is None:
                    or_tables = set(sub_tables)
                else:
                    or_tables &= sub_tables
            return or_tables or set()

        if isinstance(expr, ast.Not):
            return set()

        if isinstance(expr, ast.CompareOperation) and expr.op == ast.CompareOperationOp.Eq:
            return self._team_id_tables_from_compare(expr.left, expr.right)

        if isinstance(expr, ast.Call) and expr.name == "equals" and len(expr.args) == 2:
            return self._team_id_tables_from_compare(expr.args[0], expr.args[1])

        return set()

    def _team_id_tables_from_compare(self, left: ast.Expr, right: ast.Expr) -> set[str]:
        tables: set[str] = set()
        left_table = self._team_id_table_from_expr(left)
        right_table = self._team_id_table_from_expr(right)
        if left_table:
            tables.add(left_table)
        if right_table:
            tables.add(right_table)
        return tables

    def _team_id_table_from_expr(self, expr: ast.Expr) -> Optional[str]:
        if not isinstance(expr, ast.Field):
            return None
        if not expr.chain or str(expr.chain[-1]) != "team_id":
            return None

        return self._resolve_table_name(expr)

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
