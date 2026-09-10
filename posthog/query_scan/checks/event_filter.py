"""Decide whether a query's event filter can prune the events table by its sort key.

The events table is sorted by ``(team_id, toDate(timestamp), event, …)``, so only a condition
that compares ``event`` to fixed names lets ClickHouse skip granules. A query can look filtered
and still read every event.
"""

from typing import Literal

from posthog.hogql import ast
from posthog.hogql.feature_extractor import iter_string_constants

from posthog.dataclasses import frozen
from posthog.query_scan.explain import QueryPlan
from posthog.query_scan.tree import (
    EventsRead,
    collect_conditions,
    contains_column_of,
    find_events_reads,
    is_column_of,
    strip_aliases,
)

EventFilterClass = Literal["usable", "not_used", "none"]
EventFilterReason = Literal["in_or", "wrapped", "negated", "dynamic", "not_pruned"]

_EVENT_COLUMN = "event"

_NEGATED_OPS = frozenset(ast.NEGATED_COMPARE_OPS)
_EQUALITY_OPS = frozenset({ast.CompareOperationOp.Eq, ast.CompareOperationOp.In, ast.CompareOperationOp.GlobalIn})
_PATTERN_OPS = frozenset({ast.CompareOperationOp.Like, ast.CompareOperationOp.ILike})
# The sort order is case-sensitive, so only a case-sensitive pattern can seek in it.
_PRUNABLE_PATTERN_OPS = frozenset({ast.CompareOperationOp.Like})
# A fixed comparison the sort order cannot seek on: a regular expression has no prefix to seek
# with, and a range over event names spans the whole table in practice.
_NOT_PRUNED_OPS = frozenset(
    {
        ast.CompareOperationOp.Regex,
        ast.CompareOperationOp.IRegex,
        ast.CompareOperationOp.Gt,
        ast.CompareOperationOp.GtEq,
        ast.CompareOperationOp.Lt,
        ast.CompareOperationOp.LtEq,
    }
)

# Worst first, so taking the minimum over this order picks the worst class any read reported.
_CLASS_ORDER: tuple[EventFilterClass, ...] = ("none", "not_used", "usable")


@frozen(eq=False)
class EventFilterOutcome:
    classification: EventFilterClass
    reason: EventFilterReason | None = None
    clause: ast.Expr | None = None


def check_event_filter(tree: ast.AST, plan: QueryPlan | None = None) -> EventFilterOutcome:
    reads = find_events_reads(tree)
    if not reads:
        return EventFilterOutcome(classification="usable")

    outcomes = [_classify_read(read, collect_conditions(tree, read)) for read in reads]
    worst = min(outcomes, key=lambda outcome: _CLASS_ORDER.index(outcome.classification))

    key_used = plan.event_key_used() if plan is not None else None
    if key_used is True and worst.reason != "negated":
        # ClickHouse reports what it really used, so it overrules the tree. A negation is the
        # exception, because `event` enters the key condition but excluding a value skips only the
        # granules made entirely of that value.
        return EventFilterOutcome(classification="usable")
    if key_used is False and worst.classification == "usable":
        # The plan says some read did not prune, not which one, so name a clause only when there
        # is a single read it could belong to. A read the tree already faulted keeps its own
        # reason, which says more.
        return EventFilterOutcome(
            classification="not_used", reason="not_pruned", clause=worst.clause if len(reads) == 1 else None
        )
    return worst


def _classify_read(read: EventsRead, conditions: list[ast.Expr]) -> EventFilterOutcome:
    matched = _classify_from_tree(read, conditions)
    return matched if matched is not None else EventFilterOutcome(classification="none")


def _classify_from_tree(read: EventsRead, conditions: list[ast.Expr]) -> EventFilterOutcome | None:
    """``None`` when nothing in ``conditions`` says anything about this read's ``event`` column.

    A conjunction is classified the same way as the whole condition list, so a branch of an OR
    that never names the column stays unrelated instead of counting as a filter inside an OR.
    """
    best: EventFilterOutcome | None = None
    for term in conditions:
        classified = _classify_term(term, read)
        if classified is None:
            continue
        if classified.classification == "usable":
            return classified
        if best is None:
            best = classified
    return best


def _classify_term(term: ast.Expr, read: EventsRead) -> EventFilterOutcome | None:
    """``None`` when the term says nothing about this read's ``event`` column."""
    term = strip_aliases(term)

    if isinstance(term, ast.And):
        return _classify_from_tree(read, [strip_aliases(child) for child in term.exprs])

    if isinstance(term, ast.Or):
        return _classify_or(term, read)

    if isinstance(term, ast.Not):
        inner = _classify_term(term.expr, read)
        if inner is None:
            return None
        return EventFilterOutcome(classification="not_used", reason="negated", clause=term)

    if isinstance(term, ast.CompareOperation):
        return _classify_compare(term, read)

    if contains_column_of(term, read, _EVENT_COLUMN):
        # A bare call over `event`, for example `match(event, '…')`.
        return EventFilterOutcome(classification="not_used", reason="wrapped", clause=term)
    return None


def _classify_or(term: ast.Or, read: EventsRead) -> EventFilterOutcome | None:
    branches = [_classify_term(branch, read) for branch in term.exprs]
    if all(branch is None for branch in branches):
        return None
    if all(branch is not None and branch.classification == "usable" for branch in branches):
        # Every branch names events, so the OR is still a list of event names.
        return EventFilterOutcome(classification="usable", clause=term)
    return EventFilterOutcome(classification="not_used", reason="in_or", clause=term)


def _classify_compare(node: ast.CompareOperation, read: EventsRead) -> EventFilterOutcome | None:
    for field_side, value_side in ((node.left, node.right), (node.right, node.left)):
        if is_column_of(field_side, read, _EVENT_COLUMN):
            return _classify_event_compare(node, value_side)
        if contains_column_of(field_side, read, _EVENT_COLUMN):
            return EventFilterOutcome(classification="not_used", reason="wrapped", clause=node)
    return None


def _classify_event_compare(node: ast.CompareOperation, value_side: ast.Expr) -> EventFilterOutcome:
    if node.op in _NEGATED_OPS:
        return EventFilterOutcome(classification="not_used", reason="negated", clause=node)
    if node.op in _EQUALITY_OPS and _is_constant(value_side):
        return EventFilterOutcome(classification="usable", clause=node)
    if node.op in _PATTERN_OPS and _is_constant(value_side):
        pattern = next(iter_string_constants(value_side), None)
        if node.op in _PRUNABLE_PATTERN_OPS and pattern is not None and not pattern.startswith("%"):
            return EventFilterOutcome(classification="usable", clause=node)
        # A leading wildcard leaves no prefix for the sort order to seek on, and an ILIKE pattern
        # has no case-sensitive prefix at all.
        return EventFilterOutcome(classification="not_used", reason="not_pruned", clause=node)
    if node.op not in _NOT_PRUNED_OPS and _is_data(value_side):
        # `dynamic` tells the person their filter compares `event` to a column or a subquery, so
        # only that shape may take it.
        return EventFilterOutcome(classification="not_used", reason="dynamic", clause=node)
    return EventFilterOutcome(classification="not_used", reason="not_pruned", clause=node)


def _is_data(expr: ast.Expr) -> bool:
    """Whether the other side of the comparison is read from the data rather than written out."""
    expr = strip_aliases(expr)
    return isinstance(expr, ast.Field | ast.SelectQuery | ast.SelectSetQuery)


def _is_constant(expr: ast.Expr) -> bool:
    expr = strip_aliases(expr)
    if isinstance(expr, ast.Constant):
        return True
    if isinstance(expr, ast.Tuple | ast.Array):
        return all(_is_constant(item) for item in expr.exprs)
    return False
