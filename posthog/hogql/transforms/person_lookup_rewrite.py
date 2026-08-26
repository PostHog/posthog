"""Rewrite single-person lookups on `events` to read the `persons` table.

`SELECT any(person.properties) FROM events WHERE person.id = 'x'` scans the team's
entire event history, because a person filter without a timestamp bound cannot use
the events table's date-first sort key. Production queries of this shape read
hundreds of gigabytes to fetch one person's properties. The same answer comes from
the `persons` table in milliseconds, so when a select reads only person-sourced
fields and filters only on person identity, this pass retargets it.

`any(person_properties)` on events returns an arbitrary event-time snapshot, so the
rewrite changes results from "some historical snapshot" to "current properties".
That is within the contract's slop: with no ORDER BY, no caller can depend on which
snapshot `any()` picks. A query with a timestamp bound is a deliberate era-scoped
read and is never rewritten.

Exports:
* rewrite_person_lookups
"""

from typing import Optional, TypeVar

from prometheus_client import Counter

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.visitor import CloningVisitor

_T_AST = TypeVar("_T_AST", bound=AST)

PERSON_LOOKUP_REWRITE_COUNTER = Counter(
    "posthog_hogql_person_lookup_rewrites_total",
    "Single-person lookups on events rewritten to read the persons table.",
)

# Person-sourced fields that exist on the persons table under the same name.
_PERSON_FIELDS = {"properties", "id", "created_at"}

# Aggregate wrappers a lookup query uses to collapse many event rows into one.
# On a one-person persons read they are harmless, so `any` is kept and `argMax`
# (whose sort key was an events column) is converted to `any`.
_LOOKUP_AGGREGATES = {"any", "argMax"}


def _events_alias(join: ast.JoinExpr) -> Optional[str]:
    """The alias the query can prefix fields with, when FROM is the bare events table."""
    if (
        join.next_join is not None
        or join.sample is not None
        or join.table_final
        or not isinstance(join.table, ast.Field)
        or join.table.chain != ["events"]
    ):
        return None
    return join.alias or "events"


def _person_subchain(field: ast.Field, alias: str) -> Optional[list[str | int]]:
    """The chain below `person` when the field is person-sourced, e.g. ["properties", "email"]."""
    chain = list(field.chain)
    if chain and chain[0] == alias:
        chain = chain[1:]
    if len(chain) >= 2 and chain[0] == "person" and chain[1] in _PERSON_FIELDS:
        return chain[1:]
    return None


def _is_distinct_id_field(field: ast.Field, alias: str) -> bool:
    chain = list(field.chain)
    if chain and chain[0] == alias:
        chain = chain[1:]
    return chain == ["distinct_id"]


def _flatten_and(node: Optional[ast.Expr]) -> Optional[list[ast.Expr]]:
    if node is None:
        return []
    if isinstance(node, ast.And):
        flattened: list[ast.Expr] = []
        for expr in node.exprs:
            child = _flatten_and(expr)
            if child is None:
                return None
            flattened.extend(child)
        return flattened
    if isinstance(node, ast.Call) and node.name == "and":
        return _flatten_and(ast.And(exprs=node.args))
    if isinstance(node, ast.CompareOperation):
        return [node]
    return None


def _rewrite_select_expr(expr: ast.Expr, alias: str) -> Optional[ast.Expr]:
    """The persons-table version of a select column, or None when ineligible."""
    if isinstance(expr, ast.Alias):
        inner = _rewrite_select_expr(expr.expr, alias)
        if inner is None:
            return None
        return ast.Alias(alias=expr.alias, expr=inner)
    if isinstance(expr, ast.Field):
        subchain = _person_subchain(expr, alias)
        if subchain is None:
            return None
        return ast.Field(chain=subchain)
    if isinstance(expr, ast.Call) and expr.name in _LOOKUP_AGGREGATES and not expr.distinct and expr.args:
        first = expr.args[0]
        if not isinstance(first, ast.Field):
            return None
        subchain = _person_subchain(first, alias)
        if subchain is None:
            return None
        # argMax's sort key was an events column; on a single persons row `any` is equivalent.
        return ast.Call(name="any", args=[ast.Field(chain=subchain)])
    return None


def _rewrite_predicate(expr: ast.Expr, alias: str) -> Optional[ast.Expr]:
    """The persons-table version of a WHERE predicate, or None when ineligible."""
    if not isinstance(expr, ast.CompareOperation) or expr.op != ast.CompareOperationOp.Eq:
        return None
    if not isinstance(expr.left, ast.Field) or not isinstance(expr.right, ast.Constant):
        return None
    if _person_subchain(expr.left, alias) == ["id"]:
        return ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["id"]), right=expr.right)
    if _is_distinct_id_field(expr.left, alias):
        return ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["id"]),
            right=ast.SelectQuery(
                select=[ast.Field(chain=["person_id"])],
                select_from=ast.JoinExpr(table=ast.Field(chain=["person_distinct_ids"])),
                where=ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["distinct_id"]),
                    right=expr.right,
                ),
            ),
        )
    return None


def _try_rewrite(node: ast.SelectQuery) -> Optional[ast.SelectQuery]:
    if (
        node.ctes
        or node.distinct
        or node.array_join_op
        or node.window_exprs
        or node.prewhere
        or node.having
        or node.qualify
        or node.group_by
        or node.order_by
        or node.limit_by
        or node.view_name
        or node.select_from is None
    ):
        return None

    alias = _events_alias(node.select_from)
    if alias is None:
        return None

    select = [_rewrite_select_expr(expr, alias) for expr in node.select]
    if not select or any(expr is None for expr in select):
        return None

    predicates = _flatten_and(node.where)
    if predicates is None or not predicates:
        return None
    where = [_rewrite_predicate(expr, alias) for expr in predicates]
    narrowed_where = [expr for expr in where if expr is not None]
    if len(narrowed_where) != len(where):
        return None

    rewritten_where: ast.Expr = narrowed_where[0] if len(narrowed_where) == 1 else ast.And(exprs=narrowed_where)
    return ast.SelectQuery(
        select=[expr for expr in select if expr is not None],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=rewritten_where,
        limit=node.limit,
        offset=node.offset,
        settings=node.settings,
    )


class _PersonLookupRewriter(CloningVisitor):
    def visit_select_query(self, node: ast.SelectQuery):
        rewritten = _try_rewrite(node)
        if rewritten is not None:
            PERSON_LOOKUP_REWRITE_COUNTER.inc()
            return rewritten
        return super().visit_select_query(node)


def rewrite_person_lookups(node: _T_AST) -> _T_AST:
    return _PersonLookupRewriter(clear_types=True, clear_locations=False).visit(node)
