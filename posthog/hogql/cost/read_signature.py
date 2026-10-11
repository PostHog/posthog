"""Digest of the data a HogQL query reads.

Two queries share a read signature when they read the same tables and, on the events table, the same
day-rounded ``timestamp`` bounds and the same event names. The events table is sorted by team, then day, then
event name, so those conditions decide which part of the table a query reads. Every other filter is ignored,
because it is evaluated on rows inside that part. Bounds are rounded to the day so that two charts refreshed a
few minutes apart, whose ranges differ only in the time of day, still match.

A ``timestamp`` or ``event`` condition in a form this module does not recognize is hashed into the signature
instead of dropped. Dropping it would report two queries with different relative windows as the same read.

The HogQL executor emits it as the ``read_signature`` query tag, which ClickHouse records in ``log_comment``.
Grouping the query log by it, within one dashboard load, shows how much work separate queries repeat over the
same data.
"""

import json
import hashlib
from datetime import date, datetime

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor, clone_expr

_EVENTS_TABLE = "events"
_TIMESTAMP_FIELD = "timestamp"
_EVENT_FIELD = "event"

_LOWER_BOUND_OPS = frozenset({ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq})
_UPPER_BOUND_OPS = frozenset({ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq})


def _digest(text: str, length: int) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:length]


def _opaque(expr: ast.Expr) -> str:
    # Source positions and resolved types differ between two parses of the same text, so they are cleared
    # before the expression is hashed.
    return "?" + _digest(repr(clone_expr(expr, clear_types=True, clear_locations=True)), 8)


def _day(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date().isoformat()
        except ValueError:
            return None
    return None


def _is_events_field(expr: ast.Expr, name: str, events_aliases: set[str]) -> bool:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    if not isinstance(expr, ast.Field):
        return False
    chain = expr.chain
    if len(chain) == 1:
        return chain[0] == name
    return len(chain) == 2 and chain[0] in events_aliases and chain[1] == name


def _bound(expr: ast.Expr) -> str:
    if isinstance(expr, ast.Constant):
        day = _day(expr.value)
        return day if day is not None else _opaque(expr)
    if (
        isinstance(expr, ast.Call)
        and expr.name.lower() == "todatetime"
        and expr.args
        and isinstance(expr.args[0], ast.Constant)
    ):
        day = _day(expr.args[0].value)
        if day is not None:
            return day
    return _opaque(expr)


def _string_constants(expr: ast.Expr) -> set[str] | None:
    if isinstance(expr, ast.Constant):
        return {expr.value} if isinstance(expr.value, str) else None
    if isinstance(expr, ast.Tuple | ast.Array):
        names: set[str] = set()
        for item in expr.exprs:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                return None
            names.add(item.value)
        return names
    return None


def _event_names(expr: ast.Expr, events_aliases: set[str]) -> set[str] | None:
    if isinstance(expr, ast.Or):
        names: set[str] = set()
        for branch in expr.exprs:
            branch_names = _event_names(branch, events_aliases)
            if branch_names is None:
                return None
            names |= branch_names
        return names
    if not isinstance(expr, ast.CompareOperation):
        return None
    if expr.op == ast.CompareOperationOp.Eq:
        for field_side, value_side in ((expr.left, expr.right), (expr.right, expr.left)):
            if _is_events_field(field_side, _EVENT_FIELD, events_aliases) and isinstance(value_side, ast.Constant):
                return _string_constants(value_side)
        return None
    if expr.op == ast.CompareOperationOp.In and _is_events_field(expr.left, _EVENT_FIELD, events_aliases):
        return _string_constants(expr.right)
    return None


class _EventsFieldFinder(TraversingVisitor):
    def __init__(self, events_aliases: set[str]) -> None:
        super().__init__()
        self.events_aliases = events_aliases
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        if _is_events_field(node, _TIMESTAMP_FIELD, self.events_aliases) or _is_events_field(
            node, _EVENT_FIELD, self.events_aliases
        ):
            self.found = True


def _conjuncts(expr: ast.Expr | None) -> list[ast.Expr]:
    if expr is None:
        return []
    if isinstance(expr, ast.And):
        return [conjunct for item in expr.exprs for conjunct in _conjuncts(item)]
    return [expr]


def _describe_events_read(select: ast.SelectQuery, events_aliases: set[str], join_conditions: list[ast.Expr]) -> str:
    lower: set[str] = set()
    upper: set[str] = set()
    # One entry for each condition, because two conditions on the event name narrow each other.
    event_filters: set[str] = set()
    unrecognized: set[str] = set()

    for conjunct in [
        *_conjuncts(select.where),
        *_conjuncts(select.prewhere),
        *[conjunct for condition in join_conditions for conjunct in _conjuncts(condition)],
    ]:
        if (
            isinstance(conjunct, ast.BetweenExpr)
            and not conjunct.negated
            and _is_events_field(conjunct.expr, _TIMESTAMP_FIELD, events_aliases)
        ):
            lower.add(_bound(conjunct.low))
            upper.add(_bound(conjunct.high))
            continue

        if isinstance(conjunct, ast.CompareOperation) and conjunct.op in _LOWER_BOUND_OPS | _UPPER_BOUND_OPS:
            field_on_left = _is_events_field(conjunct.left, _TIMESTAMP_FIELD, events_aliases)
            if field_on_left or _is_events_field(conjunct.right, _TIMESTAMP_FIELD, events_aliases):
                # `timestamp >= X` and `X <= timestamp` are the same lower bound.
                is_lower = (conjunct.op in _LOWER_BOUND_OPS) == field_on_left
                (lower if is_lower else upper).add(_bound(conjunct.right if field_on_left else conjunct.left))
                continue

        names = _event_names(conjunct, events_aliases)
        if names is not None:
            event_filters.add(json.dumps(sorted(names), separators=(",", ":")))
            continue

        finder = _EventsFieldFinder(events_aliases)
        finder.visit(conjunct)
        if finder.found:
            unrecognized.add(_opaque(conjunct))

    return "|".join(
        [
            _EVENTS_TABLE,
            ",".join(sorted(lower)),
            ",".join(sorted(upper)),
            ";".join(sorted(event_filters)) or "*",
            ",".join(sorted(unrecognized)),
        ]
    )


class _ReadCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.reads: set[str] = set()
        self._cte_names: set[str] = set()

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A CTE name in FROM is not a table. The traversal visits the CTE body and records what it reads.
        # The names apply to this query and the queries nested in it, so a table with the same name
        # elsewhere in the statement is still recorded.
        outer_cte_names = self._cte_names
        self._cte_names = outer_cte_names | set(node.ctes or {})

        events_aliases: set[str] = set()
        join_conditions: list[ast.Expr] = []
        join = node.select_from
        while join is not None:
            if isinstance(join.table, ast.Field):
                table = ".".join(str(part) for part in join.table.chain)
                if table not in self._cte_names:
                    if table == _EVENTS_TABLE:
                        events_aliases.add(join.alias or _EVENTS_TABLE)
                    else:
                        self.reads.add(table)
            if join.constraint is not None and join.constraint.constraint_type == "ON":
                join_conditions.append(join.constraint.expr)
            join = join.next_join

        if events_aliases:
            self.reads.add(_describe_events_read(node, events_aliases, join_conditions))

        try:
            super().visit_select_query(node)
        finally:
            self._cte_names = outer_cte_names

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        initial = node.initial_select_query
        if not isinstance(initial, ast.SelectQuery) or not initial.ctes:
            super().visit_select_set_query(node)
            return

        outer_cte_names = self._cte_names
        self._cte_names = outer_cte_names | set(initial.ctes)
        try:
            super().visit_select_set_query(node)
        finally:
            self._cte_names = outer_cte_names


def read_signature(node: ast.SelectQuery | ast.SelectSetQuery) -> str | None:
    """Return a 16-hex-character digest of what the query reads, or None when it reads no table."""
    collector = _ReadCollector()
    collector.visit(node)
    if not collector.reads:
        return None
    return _digest("\x1f".join(sorted(collector.reads)), 16)
