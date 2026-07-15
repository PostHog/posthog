"""Structural fingerprint for HogQL queries: spelling differences (literals,
alias names, formatting, qualification) are canonicalized away and the result
hashed, so query_log rows can be grouped into patterns for performance triage.
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
        self._from_scopes: list[tuple[dict[str, str], int]] = []
        # Never popped: CTEs parse onto the first UNION branch but are referenced from later ones.
        self._cte_renames: dict[str, str] = {}

    def visit_constant(self, node: ast.Constant):
        return ast.Constant(value="?")

    def visit_placeholder(self, node: ast.Placeholder):
        # A {template} stands for a value, and to_hogql cannot print it unresolved.
        return ast.Constant(value="?")

    def visit_alias(self, node: ast.Alias):
        return self.visit(node.expr)

    def visit_call(self, node: ast.Call):
        cloned = super().visit_call(node)
        # Lowercase only when the lowered name resolves: toIntervalDay must keep its spelling to print.
        lowered = cloned.name.lower()
        if lowered != cloned.name and (
            find_hogql_function(lowered) or find_hogql_aggregation(lowered) or find_hogql_posthog_function(lowered)
        ):
            cloned.name = lowered
        if cloned.name == "count" and any(isinstance(arg, ast.Field) and arg.chain == ["*"] for arg in cloned.args):
            cloned.args = []
        return cloned

    def visit_select_query(self, node: ast.SelectQuery):
        node = _resolve_positional_refs(node)
        if node.ctes:
            for name in node.ctes:
                self._cte_renames.setdefault(name, f"cte{len(self._cte_renames)}")
        self._from_scopes.append(_collect_from_scope(node))
        try:
            cloned = super().visit_select_query(node)
        finally:
            self._from_scopes.pop()
        if cloned.ctes:
            cloned.ctes = {
                self._cte_renames[name]: replace(cte, name=self._cte_renames[name]) for name, cte in cloned.ctes.items()
            }
        return cloned

    def visit_join_expr(self, node: ast.JoinExpr):
        cloned = super().visit_join_expr(node)
        cloned.alias = None
        if self._from_scopes:
            renames, source_count = self._from_scopes[-1]
            if source_count > 1:
                name = node.alias or (
                    str(node.table.chain[-1]) if isinstance(node.table, ast.Field) and node.table.chain else None
                )
                cloned.alias = renames.get(name) if name else None
        return cloned

    def visit_field(self, node: ast.Field):
        chain = list(node.chain)
        # Qualifiers are stripped with one source, renamed positionally with several
        # (a.id = b.id must not merge with a.id = a.id). Lazy-join hops like
        # `person.properties` are untouched because `person` is not in FROM.
        if len(chain) > 1 and self._from_scopes and str(chain[0]) in self._from_scopes[-1][0]:
            renames, source_count = self._from_scopes[-1]
            if source_count == 1:
                chain = chain[1:]
            else:
                chain[0] = renames[str(chain[0])]
        elif chain and str(chain[0]) in self._cte_renames:
            chain[0] = self._cte_renames[str(chain[0])]
        return ast.Field(chain=chain)

    def visit_array_access(self, node: ast.ArrayAccess):
        # Fold properties['foo'] into the chain before constant collapse erases the name.
        cloned = super().visit_array_access(node)
        if (
            not node.nullish
            and isinstance(node.property, ast.Constant)
            and isinstance(node.property.value, str)
            and isinstance(cloned.array, ast.Field)
        ):
            return ast.Field(chain=[*cloned.array.chain, node.property.value])
        return cloned

    def visit_tuple(self, node: ast.Tuple):
        return _collapse_constant_collection(super().visit_tuple(node))

    def visit_array(self, node: ast.Array):
        return _collapse_constant_collection(super().visit_array(node))


def _collapse_constant_collection(cloned: ast.Tuple | ast.Array) -> ast.Expr:
    if cloned.exprs and all(isinstance(expr, ast.Constant) for expr in cloned.exprs):
        return ast.Constant(value="?")
    return cloned


def _collect_from_scope(node: ast.SelectQuery) -> tuple[dict[str, str], int]:
    renames: dict[str, str] = {}
    source_count = 0
    join = node.select_from
    while join is not None:
        positional = f"t{source_count}"
        if join.alias:
            renames.setdefault(join.alias, positional)
        if isinstance(join.table, ast.Field) and join.table.chain:
            renames.setdefault(str(join.table.chain[-1]), positional)
        source_count += 1
        join = join.next_join
    return renames, source_count


def _resolve_positional_refs(node: ast.SelectQuery) -> ast.SelectQuery:
    # GROUP BY 1 / ORDER BY cnt must resolve to the select expression before
    # constants collapse and aliases are dropped.
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
    digest = hashlib.sha256(f"{FINGERPRINT_VERSION}:{canonical.to_hogql()}".encode()).hexdigest()[:16]
    return f"{FINGERPRINT_VERSION}:{digest}"
