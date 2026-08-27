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
snapshot `any()` picks. Everything with firmer semantics is ineligible: a timestamp
bound (deliberate era-scoped read), a bare field (one row per event), `argMax(...,
timestamp)` (deterministically the latest snapshot), and decorated calls.

Exports:
* rewrite_person_lookups
"""

from typing import Optional, TypeVar

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.visitor import CloningVisitor

from posthog.clickhouse.query_tagging import tag_queries

_T_AST = TypeVar("_T_AST", bound=AST)

# Person-sourced fields that exist on the persons table under the same name.
_PERSON_FIELDS = {"properties", "id", "created_at"}


def _events_alias(join: ast.JoinExpr) -> Optional[str]:
    """The alias the query can prefix fields with, when FROM is the bare events table."""
    if (
        join.next_join is not None
        or join.sample is not None
        or join.table_final
        or join.table_args is not None
        or join.column_aliases
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
    """The persons-table version of a select column, or None when ineligible.

    Only an undecorated `any(person_field)` qualifies. A bare field returns one row
    per matching event, so retargeting it would change cardinality, and `argMax(...,
    timestamp)` deterministically returns the latest event-time snapshot, which the
    current-person row does not preserve. Call decorations (DISTINCT, FILTER, ORDER
    BY, parametric parameters) all change what `any` returns, so their presence
    disqualifies rather than being silently dropped.
    """
    if isinstance(expr, ast.Alias):
        inner = _rewrite_select_expr(expr.expr, alias)
        if inner is None:
            return None
        return ast.Alias(alias=expr.alias, expr=inner)
    if (
        isinstance(expr, ast.Call)
        and expr.name == "any"
        and not expr.distinct
        and len(expr.args) == 1
        and not expr.params
        and not expr.within_group
        and not expr.order_by
        and expr.filter_expr is None
    ):
        first = expr.args[0]
        if not isinstance(first, ast.Field):
            return None
        subchain = _person_subchain(first, alias)
        if subchain is None:
            return None
        # Table-qualified so an output alias like `AS created_at` cannot capture the field.
        return ast.Call(name="any", args=[ast.Field(chain=["persons", *subchain])])
    return None


def _rewrite_predicate(expr: ast.Expr, alias: str) -> Optional[ast.Expr]:
    """The persons-table version of a WHERE predicate, or None when ineligible."""
    if not isinstance(expr, ast.CompareOperation) or expr.op != ast.CompareOperationOp.Eq:
        return None
    if not isinstance(expr.left, ast.Field) or not isinstance(expr.right, ast.Constant):
        return None
    # Table-qualified so a select alias named `id` cannot capture the field.
    if _person_subchain(expr.left, alias) == ["id"]:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["persons", "id"]), right=expr.right
        )
    if _is_distinct_id_field(expr.left, alias):
        return ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["persons", "id"]),
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
        or node.group_by_mode
        or node.order_by
        or node.limit_by
        or node.limit_percent
        or node.limit_with_ties
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

    # Exactly one identity predicate: conjunctions of identifiers have event-existence
    # semantics (distinct_id = 'a' AND distinct_id = 'b' matches no event, but both IDs
    # can resolve to the same current person).
    predicates = _flatten_and(node.where)
    if predicates is None or len(predicates) != 1:
        return None
    rewritten_where = _rewrite_predicate(predicates[0], alias)
    if rewritten_where is None:
        return None

    return ast.SelectQuery(
        select=[expr for expr in select if expr is not None],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=rewritten_where,
        limit=node.limit,
        offset=node.offset,
        settings=node.settings,
    )


# The rewrite reads `events` and emits `persons` and `person_distinct_ids`, all matched
# by unresolved name, so a CTE shadowing any of them disqualifies the enclosed scope.
_SHADOWABLE_NAMES = {"events", "persons", "person_distinct_ids"}


class _PersonLookupRewriter(CloningVisitor):
    def __init__(self):
        super().__init__(clear_types=True, clear_locations=False)
        self._cte_scope_names: list[set[str]] = []

    def _push_scope(self, names: set[str]):
        self._cte_scope_names.append(names & _SHADOWABLE_NAMES)

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        # CTEs declared on one branch stay in SQL scope for the later set-operation
        # branches, so hold every branch's names for the whole set traversal.
        names: set[str] = set()
        for select_query in node.select_queries():
            if isinstance(select_query, ast.SelectQuery) and select_query.ctes:
                names.update(select_query.ctes.keys())
        self._push_scope(names)
        try:
            return super().visit_select_set_query(node)
        finally:
            self._cte_scope_names.pop()

    def visit_select_query(self, node: ast.SelectQuery):
        # The resolver inherits CTEs from enclosing scopes, so a subquery's `events` can
        # refer to an outer `WITH events AS (...)` rather than the real table.
        if not any(self._cte_scope_names):
            rewritten = _try_rewrite(node)
            if rewritten is not None:
                tag_queries(person_lookup_rewrite=1)
                return rewritten
        self._push_scope(set(node.ctes.keys()) if node.ctes else set())
        try:
            return super().visit_select_query(node)
        finally:
            self._cte_scope_names.pop()


def rewrite_person_lookups(node: _T_AST) -> _T_AST:
    return _PersonLookupRewriter().visit(node)
