"""Rewrite single-person property lookups on `events` to read the `persons` table.

`SELECT any(person.properties.email) FROM events WHERE person.id = 'x'` scans the
team's entire event history, because a person filter without a timestamp bound cannot
use the events table's date-first sort key. Production queries of this shape read
hundreds of gigabytes to fetch one person's properties. The same answer comes from
the `persons` table in milliseconds, so when a select reads only person property
keys and filters only on `person.id`, this pass retargets it.

`any(person.properties.<key>)` on events returns an arbitrary event-time snapshot,
so the rewrite changes results from "some historical snapshot" to "current value".
That is within the contract's slop: with no ORDER BY, no caller can depend on which
snapshot `any()` picks. Everything with firmer semantics is ineligible: a timestamp
bound (deliberate era-scoped read), a bare field (one row per event), `argMax(...,
timestamp)` (deterministically the latest snapshot), and decorated calls.

Only property-key extractions are eligible, because they are nullable on both the
events path and the persons path in every person-on-events mode, so values and
response types match exactly. Base fields (`person.id`, `person.created_at`, whole
`person.properties`) are non-nullable on some paths and not others, so their
no-match results diverge; they stay on events. `distinct_id = const` predicates
also stay on events until the person_distinct_ids lazy table can push the filter
below its aggregation — without that, the emitted lookup aggregates the team's
whole distinct-id history.

Exports:
* rewrite_person_lookups
"""

import dataclasses
from typing import Optional, TypeVar

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.escape_sql import escape_hogql_identifier
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

_T_AST = TypeVar("_T_AST", bound=AST)

# Position and type metadata carry no query semantics.
_METADATA_FIELDS = frozenset({"start", "end", "type"})

_HANDLED_SELECT_FIELDS = _METADATA_FIELDS | {"select", "select_from", "where", "limit", "offset", "settings"}
_HANDLED_FROM_FIELDS = _METADATA_FIELDS | {"table", "alias"}
_HANDLED_ANY_CALL_FIELDS = _METADATA_FIELDS | {"name", "args"}


def _unhandled_fields_empty(node: AST, handled: frozenset[str]) -> bool:
    """Default deny: every field the rewrite does not explicitly copy or check must be
    empty — including fields the AST grows after this pass was written. An enumerated
    disqualifier list silently admits new clauses; this admits nothing by omission."""
    return all(not getattr(node, f.name) for f in dataclasses.fields(node) if f.name not in handled)


def _events_alias(join: ast.JoinExpr) -> Optional[str]:
    """The alias the query can prefix fields with, when FROM is the bare events table."""
    if (
        not _unhandled_fields_empty(join, _HANDLED_FROM_FIELDS)
        or not isinstance(join.table, ast.Field)
        or join.table.chain != ["events"]
    ):
        return None
    return join.alias or "events"


def _person_subchain(field: ast.Field, alias: str) -> Optional[list[str | int]]:
    """The chain below `person`, e.g. ["properties", "email"] or ["id"]."""
    chain = list(field.chain)
    if chain and chain[0] == alias:
        chain = chain[1:]
    if len(chain) >= 2 and chain[0] == "person":
        return chain[1:]
    return None


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


def _rewrite_any_call(expr: ast.Expr, alias: str) -> Optional[ast.Call]:
    """The persons-table version of an `any(person.properties.<key>)` call, or None.

    Only an undecorated `any` over a property-key extraction qualifies. A bare field
    returns one row per matching event, so retargeting it would change cardinality,
    and `argMax(..., timestamp)` deterministically returns the latest event-time
    snapshot, which the current-person row does not preserve. Call decorations
    (DISTINCT, FILTER, ORDER BY, parametric parameters) all change what `any`
    returns, so any field beyond the name and its single argument disqualifies
    rather than being silently dropped.
    """
    if (
        isinstance(expr, ast.Call)
        and expr.name == "any"
        and len(expr.args) == 1
        and _unhandled_fields_empty(expr, _HANDLED_ANY_CALL_FIELDS)
    ):
        first = expr.args[0]
        if not isinstance(first, ast.Field):
            return None
        subchain = _person_subchain(first, alias)
        if subchain is None or len(subchain) < 2 or subchain[0] != "properties":
            return None
        # Table-qualified so an output alias like `AS properties` cannot capture the field.
        return ast.Call(name="any", args=[ast.Field(chain=["persons", *subchain])])
    return None


def _implicit_column_name(call: ast.Call) -> Optional[str]:
    """The column name the query had before the rewrite, for an unaliased eligible call.

    The resolver and the response derive an unaliased column's name from the printed
    HogQL of the expression, so the rewrite must pin that exact string as an alias or
    outer queries referencing the column break and `response.columns` changes.
    """
    field = call.args[0]
    if not isinstance(field, ast.Field) or any(isinstance(part, str) and "%" in part for part in field.chain):
        return None
    printed_chain = ".".join(
        str(part) if isinstance(part, int) else escape_hogql_identifier(part) for part in field.chain
    )
    return f"any({printed_chain})"


def _rewrite_select_expr(expr: ast.Expr, alias: str) -> Optional[ast.Alias]:
    if isinstance(expr, ast.Alias):
        inner = _rewrite_any_call(expr.expr, alias)
        if inner is None:
            return None
        return ast.Alias(alias=expr.alias, expr=inner)
    if not isinstance(expr, ast.Call):
        return None
    inner = _rewrite_any_call(expr, alias)
    if inner is None:
        return None
    implicit_name = _implicit_column_name(expr)
    if implicit_name is None:
        return None
    return ast.Alias(alias=implicit_name, expr=inner)


def _rewrite_predicate(expr: ast.Expr, alias: str) -> Optional[ast.Expr]:
    """The persons-table version of the WHERE predicate, or None when ineligible."""
    if not isinstance(expr, ast.CompareOperation) or expr.op != ast.CompareOperationOp.Eq:
        return None
    if not isinstance(expr.left, ast.Field) or not isinstance(expr.right, ast.Constant):
        return None
    if _person_subchain(expr.left, alias) != ["id"]:
        return None
    # Table-qualified so a select alias named `id` cannot capture the field.
    return ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["persons", "id"]), right=expr.right)


def _try_rewrite(node: ast.SelectQuery) -> Optional[ast.SelectQuery]:
    if not _unhandled_fields_empty(node, _HANDLED_SELECT_FIELDS) or node.select_from is None:
        return None

    alias = _events_alias(node.select_from)
    if alias is None:
        return None

    select_exprs: list[ast.Expr] = []
    aliases: list[str] = []
    for expr in node.select:
        rewritten_expr = _rewrite_select_expr(expr, alias)
        if rewritten_expr is None:
            return None
        select_exprs.append(rewritten_expr)
        aliases.append(rewritten_expr.alias)
    # Pinning implicit names makes duplicated unaliased expressions collide as
    # explicit aliases, which the resolver rejects; the original compiled fine.
    if not aliases or len(set(aliases)) != len(aliases):
        return None

    # Exactly one identity predicate: conjunctions of identifiers have event-existence
    # semantics that current-person membership does not preserve.
    predicates = _flatten_and(node.where)
    if predicates is None or len(predicates) != 1:
        return None
    rewritten_where = _rewrite_predicate(predicates[0], alias)
    if rewritten_where is None:
        return None

    return ast.SelectQuery(
        select=select_exprs,
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        where=rewritten_where,
        limit=node.limit,
        offset=node.offset,
        settings=node.settings,
    )


# The rewrite reads `events` and emits `persons`, both matched by unresolved name,
# so a CTE shadowing either name disqualifies the enclosed scope.
_SHADOWABLE_NAMES = {"events", "persons"}


class _ContainsBareEventsSource(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.found = False

    def visit_join_expr(self, node: ast.JoinExpr):
        if isinstance(node.table, ast.Field) and node.table.chain == ["events"]:
            self.found = True
        super().visit_join_expr(node)


class _PersonLookupRewriter(CloningVisitor):
    def __init__(self):
        super().__init__(clear_types=True, clear_locations=False)
        self._cte_scope_names: list[set[str]] = []
        self.rewrote = False

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
                self.rewrote = True
                return rewritten
        self._push_scope(set(node.ctes.keys()) if node.ctes else set())
        try:
            return super().visit_select_query(node)
        finally:
            self._cte_scope_names.pop()


def rewrite_person_lookups(node: _T_AST) -> tuple[_T_AST, bool]:
    # A read-only scan first: queries that never read the bare events table (the
    # overwhelming majority) skip the full clone the rewriting visitor would allocate.
    scan = _ContainsBareEventsSource()
    scan.visit(node)
    if not scan.found:
        return node, False
    rewriter = _PersonLookupRewriter()
    result = rewriter.visit(node)
    return result, rewriter.rewrote
