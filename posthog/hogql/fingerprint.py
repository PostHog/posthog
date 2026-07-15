"""Structural fingerprint for HogQL queries.

Two queries share a fingerprint when they do the same work with different
values: literals, alias names, formatting, table-alias qualification, and
positional GROUP BY / ORDER BY references are canonicalized away, while
tables, columns, functions, and operators are kept. Tagged into query_log
so query patterns can be grouped for performance triage regardless of how
each caller happened to write the SQL.
"""

import hashlib
from dataclasses import replace

from posthog.hogql import ast
from posthog.hogql.functions.mapping import find_hogql_aggregation, find_hogql_function, find_hogql_posthog_function
from posthog.hogql.visitor import CloningVisitor

# Part of the hash input: bump when canonicalization rules change so old and
# new fingerprints never mix within one series.
FINGERPRINT_VERSION = "v1"


class _Canonicalizer(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=True, clear_locations=True)
        self._from_names: list[set[str]] = []

    def visit_constant(self, node: ast.Constant):
        return ast.Constant(value="?")

    def visit_alias(self, node: ast.Alias):
        return self.visit(node.expr)

    def visit_call(self, node: ast.Call):
        cloned = super().visit_call(node)
        # The parser preserves spelling, so COUNT() and count() hash apart.
        # Lowercase only when the lowered name still resolves; case-sensitive
        # functions like toIntervalDay must keep their exact spelling to print.
        lowered = cloned.name.lower()
        if lowered != cloned.name and (
            find_hogql_function(lowered) or find_hogql_aggregation(lowered) or find_hogql_posthog_function(lowered)
        ):
            cloned.name = lowered
        return cloned

    def visit_select_query(self, node: ast.SelectQuery):
        node = _resolve_positional_refs(node)
        self._from_names.append(_collect_from_names(node))
        try:
            cloned = super().visit_select_query(node)
        finally:
            self._from_names.pop()
        return cloned

    def visit_join_expr(self, node: ast.JoinExpr):
        cloned = super().visit_join_expr(node)
        cloned.alias = None
        return cloned

    def visit_field(self, node: ast.Field):
        chain = list(node.chain)
        # `e.event` and `events.event` mean `event` once the qualifier names a
        # FROM/JOIN source of the current select; lazy-join hops like
        # `person.properties` are untouched because `person` is not in FROM.
        if len(chain) > 1 and self._from_names and str(chain[0]) in self._from_names[-1]:
            chain = chain[1:]
        return ast.Field(chain=chain)


def _collect_from_names(node: ast.SelectQuery) -> set[str]:
    names: set[str] = set()
    join = node.select_from
    while join is not None:
        if join.alias:
            names.add(join.alias)
        if isinstance(join.table, ast.Field) and join.table.chain:
            names.add(str(join.table.chain[-1]))
        join = join.next_join
    return names


def _resolve_positional_refs(node: ast.SelectQuery) -> ast.SelectQuery:
    # GROUP BY 1 / ORDER BY 2 and references to select aliases (ORDER BY cnt)
    # all mean a select column; resolve them before constants collapse to `?`
    # and aliases are dropped, so every spelling converges with the named form.
    aliases = {expr.alias: expr.expr for expr in node.select if isinstance(expr, ast.Alias)}

    def resolve(expr: ast.Expr) -> ast.Expr:
        if (
            isinstance(expr, ast.Constant)
            and isinstance(expr.value, int)
            and not isinstance(expr.value, bool)
            and 1 <= expr.value <= len(node.select)
        ):
            target = node.select[expr.value - 1]
            while isinstance(target, ast.Alias):
                target = target.expr
            return target
        if isinstance(expr, ast.Field) and len(expr.chain) == 1 and expr.chain[0] in aliases:
            return aliases[str(expr.chain[0])]
        return expr

    group_by = [resolve(expr) for expr in node.group_by] if node.group_by else node.group_by
    order_by = [replace(order, expr=resolve(order.expr)) for order in node.order_by] if node.order_by else node.order_by
    if group_by == node.group_by and order_by == node.order_by:
        return node
    return replace(node, group_by=group_by, order_by=order_by)


def fingerprint_hogql_query(query: ast.SelectQuery | ast.SelectSetQuery) -> str:
    canonical = _Canonicalizer().visit(query)
    digest = hashlib.sha1(f"{FINGERPRINT_VERSION}:{canonical.to_hogql()}".encode()).hexdigest()[:16]
    return f"{FINGERPRINT_VERSION}:{digest}"
