"""What the prepared tree says about its events reads, beyond the event filter.

The plan reports an unfiltered read; it cannot say why. ``classify_event_filter`` reads the event
condition off the tree, and this module reads the rest the advice needs: whether the read carries
a start date at all, whether a property condition narrows it in place of an event name, whether
the query's shape needs all history or all events by design, and whether the read sits inside a
saved view. The trigger ships the facts with each execution and the job folds them into the plan.
"""

from __future__ import annotations

from typing import Any

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen
from posthog.query_scan.tree import (
    EventsRead,
    collect_conditions,
    contains_column_of,
    find_events_reads,
    is_column_of,
    resolve_to_table_columns,
    strip_aliases,
)

_TIMESTAMP = "timestamp"
_EVENT = "event"
_PROPERTY_COLUMNS = ("properties", "person_properties")
_ACTOR_COLUMNS = ("person_id", "distinct_id", "$session_id")

_LOWER_BOUND_ON_LEFT = frozenset({ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq, ast.CompareOperationOp.Eq})
_LOWER_BOUND_ON_RIGHT = frozenset({ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq, ast.CompareOperationOp.Eq})
_FIRST_EVENT_AGGREGATES = frozenset({"min", "minIf", "argMin", "argMinIf"})
_LAST_EVENT_AGGREGATES = frozenset({"max", "maxIf", "argMax", "argMaxIf"})
_DISTINCT_COUNTS = frozenset(
    {"uniq", "uniqIf", "uniqExact", "uniqExactIf", "uniqHLL12", "uniqCombined", "uniqCombined64", "uniqTheta"}
)
_RANKING_WINDOWS = frozenset({"row_number", "rank", "dense_rank"})


@frozen
class TreeFacts:
    """Facts about the tree's events reads, for the job to fold into the plan.

    The plan's finding is about one read and the tree cannot tell which, so each fact is worded so
    that it holds for that read whichever it is: ``timestamp_bound`` and ``property_filter`` hold
    only when every read they apply to agrees, and a by-design shape counts when any read has it.
    """

    # Every events read carries a lower bound on `timestamp`, so an unbounded read in the plan is
    # a bound ClickHouse could not use.
    timestamp_bound: bool
    # Every events read with no event condition narrows itself by a property instead.
    property_filter: bool
    # A read finds a first event ever, with `min` or `argMin` over `timestamp` or a ranking window
    # ordered by it, and has no lower bound: the answer needs all history.
    all_history: bool
    # A read groups by `event` with no event condition: the answer is the set of events itself.
    groups_by_event: bool
    # A read counts distinct actors or sessions, or finds each actor's last event, with no event
    # condition: the answer needs every event.
    counts_any_event: bool
    # The saved view every events read sits inside, when they all sit inside the same one.
    view_name: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "timestamp_bound": self.timestamp_bound,
            "property_filter": self.property_filter,
            "all_history": self.all_history,
            "groups_by_event": self.groups_by_event,
            "counts_any_event": self.counts_any_event,
            "view_name": self.view_name,
        }

    @classmethod
    def from_payload(cls, payload: object) -> TreeFacts | None:
        """None for a payload that carries no facts, so the analysis treats the tree as unknown."""
        if not isinstance(payload, dict):
            return None
        view_name = payload.get("view_name")
        return cls(
            timestamp_bound=payload.get("timestamp_bound") is True,
            property_filter=payload.get("property_filter") is True,
            all_history=payload.get("all_history") is True,
            groups_by_event=payload.get("groups_by_event") is True,
            counts_any_event=payload.get("counts_any_event") is True,
            view_name=view_name if isinstance(view_name, str) and view_name else None,
        )


@frozen
class _ReadFacts:
    timestamp_bound: bool
    event_condition: bool
    property_condition: bool
    all_history: bool
    groups_by_event: bool
    counts_any_event: bool
    view_name: str | None


def tree_facts(tree: ast.AST) -> TreeFacts | None:
    """The facts for ``tree``, or None when it reads no events."""
    reads = find_events_reads(tree)
    if not reads:
        return None
    parents = _ParentSelects()
    parents.visit(tree)
    facts = [_read_facts(read, collect_conditions(tree, read), parents) for read in reads]

    unfiltered = [read for read in facts if not read.event_condition]
    view_names = {read.view_name for read in facts}
    return TreeFacts(
        timestamp_bound=all(read.timestamp_bound for read in facts),
        property_filter=bool(unfiltered) and all(read.property_condition for read in unfiltered),
        all_history=any(read.all_history for read in facts),
        groups_by_event=any(read.groups_by_event for read in unfiltered),
        counts_any_event=any(read.counts_any_event for read in unfiltered),
        view_name=next(iter(view_names)) if len(view_names) == 1 else None,
    )


def _read_facts(read: EventsRead, conditions: list[ast.Expr], parents: _ParentSelects) -> _ReadFacts:
    timestamp_bound = any(_is_lower_bound(term, read) for term in conditions)
    select = read.select
    aggregates = _Aggregates(read)
    aggregates.visit_exprs(select.select)
    per_actor = any(_names_actor(expr, read) for expr in _group_by(select))
    return _ReadFacts(
        timestamp_bound=timestamp_bound,
        event_condition=any(contains_column_of(term, read, _EVENT) for term in conditions),
        property_condition=any(
            contains_column_of(term, read, column) for term in conditions for column in _PROPERTY_COLUMNS
        ),
        all_history=not timestamp_bound and (aggregates.first_event or aggregates.first_by_window),
        groups_by_event=any(is_column_of(expr, read, _EVENT) for expr in _group_by(select)),
        counts_any_event=aggregates.distinct_actors
        or (per_actor and aggregates.last_event)
        or aggregates.last_by_window,
        view_name=parents.view_of(select),
    )


def _is_lower_bound(term: ast.Expr, read: EventsRead) -> bool:
    """Whether ``term`` puts a start on this read's ``timestamp``. The other side is not checked:
    a bound on another column is still a bound in the tree, one the plan will show it could not
    use, which is what tells that case from no bound at all.
    """
    term = strip_aliases(term)
    if isinstance(term, ast.BetweenExpr):
        return not term.negated and contains_column_of(term.expr, read, _TIMESTAMP)
    if not isinstance(term, ast.CompareOperation):
        return False
    if term.op in _LOWER_BOUND_ON_LEFT and contains_column_of(term.left, read, _TIMESTAMP):
        return True
    return term.op in _LOWER_BOUND_ON_RIGHT and contains_column_of(term.right, read, _TIMESTAMP)


def _group_by(select: ast.SelectQuery) -> list[ast.Expr]:
    """The group-by expressions, with a positional `GROUP BY 1` resolved to the select column."""
    resolved: list[ast.Expr] = []
    for expr in select.group_by or []:
        expr = strip_aliases(expr)
        if isinstance(expr, ast.Constant) and isinstance(expr.value, int) and 1 <= expr.value <= len(select.select):
            expr = strip_aliases(select.select[expr.value - 1])
        resolved.append(expr)
    return resolved


def _names_actor(expr: ast.Expr, read: EventsRead) -> bool:
    """Whether ``expr`` reads a person, distinct id or session column. `person_id` is a column of
    the events read only in persons-on-events mode; otherwise the resolver reaches it through a
    joined distinct-id subquery, so the column is judged by its resolved name on any table."""
    finder = _ActorColumnFinder()
    finder.visit(expr)
    return finder.found


class _Aggregates(TraversingVisitor):
    """Finds the aggregates and windows over ``read`` in a select list, without entering a nested select."""

    def __init__(self, read: EventsRead) -> None:
        super().__init__()
        self.read = read
        self.first_event = False
        self.last_event = False
        self.distinct_actors = False
        self.first_by_window = False
        self.last_by_window = False

    def visit_exprs(self, exprs: list[ast.Expr]) -> None:
        for expr in exprs:
            self.visit(expr)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        return

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        return

    def visit_call(self, node: ast.Call) -> None:
        over_timestamp = any(contains_column_of(arg, self.read, _TIMESTAMP) for arg in node.args)
        if node.name in _FIRST_EVENT_AGGREGATES and over_timestamp:
            self.first_event = True
        if node.name in _LAST_EVENT_AGGREGATES and over_timestamp:
            self.last_event = True
        counts_distinct = node.name in _DISTINCT_COUNTS or (node.name == "count" and node.distinct)
        if counts_distinct and any(_names_actor(arg, self.read) for arg in node.args):
            self.distinct_actors = True
        super().visit_call(node)

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        window = node.over_expr
        if node.name in _RANKING_WINDOWS and window is not None:
            for order in window.order_by or []:
                if not contains_column_of(order.expr, self.read, _TIMESTAMP):
                    continue
                if order.order == "ASC":
                    self.first_by_window = True
                elif any(_names_actor(expr, self.read) for expr in window.partition_by or []):
                    self.last_by_window = True
        super().visit_window_function(node)


class _ActorColumnFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        if any(name in _ACTOR_COLUMNS for _, name in resolve_to_table_columns(node.type)):
            self.found = True
        super().visit_field(node)


class _ParentSelects(TraversingVisitor):
    """Maps each select to the one enclosing it, to find the saved view a read was inlined from."""

    def __init__(self) -> None:
        super().__init__()
        self._parent: dict[int, ast.SelectQuery] = {}
        self._stack: list[ast.SelectQuery] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if self._stack:
            self._parent[id(node)] = self._stack[-1]
        self._stack.append(node)
        super().visit_select_query(node)
        self._stack.pop()

    def view_of(self, select: ast.SelectQuery) -> str | None:
        """The nearest saved view ``select`` sits inside, the select itself included."""
        current: ast.SelectQuery | None = select
        while current is not None:
            if current.view_name:
                return current.view_name
            current = self._parent.get(id(current))
        return None
