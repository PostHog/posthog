"""Opt-in plans for reusing hourly conditional distinct-person states.

This module does not enable query rewriting. Callers must explicitly choose freshness,
check complete cache coverage, and retain the original query on a cache miss.
"""

from collections.abc import Callable, Iterator
from copy import deepcopy
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.visitor import clone_expr

_META = {"start", "end", "type"}
_SCALARS = {"greatest", "least", "abs", "toString", "ifNull", "coalesce"}


def _empty(value: Any) -> bool:
    return value is None or value is False or (isinstance(value, (list, dict)) and not value)


def _only(node: AST, allowed: set[str]) -> bool:
    return all(f.name in _META | allowed or _empty(getattr(node, f.name)) for f in fields(node))


def _walk(node: Any) -> Iterator[AST]:
    if isinstance(node, AST):
        yield node
        for f in fields(node):
            if f.name not in _META:
                yield from _walk(getattr(node, f.name))
    elif isinstance(node, list):
        for child in node:
            yield from _walk(child)


def _rewrite(node: Any, replace: Callable[[AST], ast.Expr | None]) -> Any:
    if isinstance(node, AST):
        replacement = replace(node)
        if replacement is not None:
            return deepcopy(replacement)
        result = deepcopy(node)
        for f in fields(node):
            if f.name not in _META:
                setattr(result, f.name, _rewrite(getattr(node, f.name), replace))
        return result
    if isinstance(node, list):
        return [_rewrite(child, replace) for child in node]
    return deepcopy(node)


def _key(node: ast.Expr) -> str:
    def canonical(value: Any) -> Any:
        if isinstance(value, AST):
            return (
                type(value).__name__,
                tuple((f.name, canonical(getattr(value, f.name))) for f in fields(value) if f.name not in _META),
            )
        if isinstance(value, list):
            return tuple(canonical(v) for v in value)
        return value

    return repr(canonical(node))


def _field(node: Any, name: str) -> bool:
    return isinstance(node, ast.Field) and node.chain == [name]


def _hour(node: Any) -> bool:
    return (
        isinstance(node, ast.Call)
        and node.name == "toStartOfHour"
        and len(node.args) == 1
        and _field(node.args[0], "timestamp")
        and _only(node, {"name", "args"})
    )


def _anchor(node: Any) -> bool:
    return (
        isinstance(node, ast.Call)
        and node.name == "toStartOfHour"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Call)
        and node.args[0].name == "now"
        and not node.args[0].args
        and _only(node, {"name", "args"})
        and _only(node.args[0], {"name", "args"})
    )


def _safe(node: ast.Expr, *, names: set[str], aggregates: bool = False) -> bool:
    for child in _walk(node):
        if isinstance(child, ast.Field):
            if child.chain not in [[n] for n in names] and not (
                names == {"person_id", "event", "properties"}
                and len(child.chain) == 2
                and child.chain[0] == "properties"
                and isinstance(child.chain[1], str)
            ):
                return False
        elif isinstance(child, ast.Call):
            if not _only(child, {"name", "args"}):
                return False
            if child.name in {"uniq", "uniqIf"} and aggregates:
                if len(child.args) != (2 if child.name == "uniqIf" else 1) or not _field(child.args[0], "person_id"):
                    return False
                if len(child.args) == 2 and not _safe(child.args[1], names={"person_id", "event", "properties"}):
                    return False
            elif child.name not in _SCALARS:
                return False
        elif not isinstance(
            child,
            (
                ast.Alias,
                ast.Constant,
                ast.ArithmeticOperation,
                ast.CompareOperation,
                ast.And,
                ast.Or,
                ast.Not,
                ast.Tuple,
                ast.Array,
            ),
        ):
            return False
    return True


@dataclass
class HourlyUniqPlan:
    original: ast.SelectQuery
    aggregation: ast.SelectQuery
    metrics: list[ast.Call]
    predicates: list[ast.Expr]
    start: datetime
    end: datetime
    timezone: str
    nested: bool

    def states(self, start: ast.Expr, end: ast.Expr) -> ast.SelectQuery:
        """One row per metric and hour, including zero-valued conditional metrics."""
        wide = ast.SelectQuery(
            select=[
                ast.Alias(alias="time_window_start", expr=parse_expr("toStartOfHour(timestamp)")),
                ast.Alias(
                    alias="states",
                    expr=ast.Array(
                        exprs=[
                            ast.Call(name="uniqStateIf" if len(m.args) == 2 else "uniqState", args=deepcopy(m.args))
                            for m in self.metrics
                        ]
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    *deepcopy(self.predicates),
                    ast.CompareOperation(
                        left=ast.Field(chain=["timestamp"]), op=ast.CompareOperationOp.GtEq, right=start
                    ),
                    ast.CompareOperation(left=ast.Field(chain=["timestamp"]), op=ast.CompareOperationOp.Lt, right=end),
                ]
            ),
            group_by=[ast.Field(chain=["time_window_start"])],
        )
        query = parse_select(
            "SELECT time_window_start AS time_window_start, tupleElement(item, 1) AS metric_index, tupleElement(item, 2) AS uniq_state FROM (SELECT time_window_start, arrayJoin(arrayZip(arrayEnumerate(states), states)) AS item FROM {wide})",
            placeholders={"wide": wide},
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    @property
    def insert_query(self) -> ast.SelectQuery:
        return clone_expr(
            self.states(parse_expr("{time_window_min}"), parse_expr("{time_window_max}")), clear_locations=True
        )

    def combine(self, states: ast.SelectQuery | ast.SelectSetQuery) -> ast.SelectQuery:
        """Reapply the original projection only after merging each conditional state."""
        indices = {_key(metric): i + 1 for i, metric in enumerate(self.metrics)}

        def replace(node: AST) -> ast.Expr | None:
            if isinstance(node, ast.Call) and _key(node) in indices:
                return parse_expr(
                    "uniqMergeIf(uniq_state, metric_index = {index})",
                    placeholders={"index": ast.Constant(value=indices[_key(node)])},
                )
            if _hour(node):
                return parse_expr("toStartOfHour(time_window_start)")
            return None

        inner = _rewrite(self.aggregation, replace)
        inner.select_from = ast.JoinExpr(table=deepcopy(states))
        inner.where = None
        inner.group_by = [ast.Field(chain=["time_window_start"])]
        if not self.nested:
            return inner
        result = deepcopy(self.original)
        assert result.select_from is not None
        result.select_from.table = inner
        return result

    def reference_query(self) -> ast.SelectQuery:
        result = deepcopy(self.original)
        inner = result.select_from.table if self.nested else result
        assert isinstance(inner, ast.SelectQuery)
        inner.where = ast.And(
            exprs=[
                *deepcopy(self.predicates),
                parse_expr(
                    "timestamp >= {start} AND timestamp < {end}",
                    placeholders={"start": ast.Constant(value=self.start), "end": ast.Constant(value=self.end)},
                ),
            ]
        )
        return result


def plan_hourly_uniq(sql: str, *, now: datetime, timezone: str) -> HourlyUniqPlan | None:
    """Fail closed; no query execution, implicit limit, or mutation of caller input."""
    try:
        if now.tzinfo is None:
            return None
        original = parse_select(sql)
        if not isinstance(original, ast.SelectQuery):
            return None
        allowed = {"select", "select_from", "where", "group_by", "order_by"}
        if not _only(original, allowed) or original.select_from is None or not _only(original.select_from, {"table"}):
            return None
        nested = isinstance(original.select_from.table, ast.SelectQuery)
        inner = original.select_from.table if nested else original
        if (
            not isinstance(inner, ast.SelectQuery)
            or not _only(inner, allowed)
            or inner.select_from is None
            or not _only(inner.select_from, {"table"})
            or not _field(inner.select_from.table, "events")
        ):
            return None
        aliases = {s.alias: s.expr for s in inner.select if isinstance(s, ast.Alias)}
        if len(aliases) != len(inner.select) or any(
            n.startswith("__") or n in {"time_window_start", "metric_index", "uniq_state", "states", "item"}
            for n in aliases
        ):
            return None
        buckets = [name for name, expr in aliases.items() if _hour(expr)]
        if len(buckets) != 1 or len(inner.group_by or []) != 1:
            return None
        group = inner.group_by[0]
        if not (_hour(group) or _field(group, buckets[0])):
            return None
        for name, expr in aliases.items():
            if name != buckets[0] and not _safe(expr, names={"person_id", "event", "properties"}, aggregates=True):
                return None
            # Every non-bucket field must occur inside a supported aggregate.
            if name != buckets[0]:
                erased = _rewrite(
                    expr,
                    lambda n: (
                        ast.Constant(value=0) if isinstance(n, ast.Call) and n.name in {"uniq", "uniqIf"} else None
                    ),
                )
                if not _safe(erased, names=set()):
                    return None
        if nested:
            if original.where or original.group_by or not all(_safe(s, names=set(aliases)) for s in original.select):
                return None
        for query in [inner, original]:
            for order in query.order_by or []:
                order_names = set(aliases) | {s.alias for s in original.select if isinstance(s, ast.Alias)}
                if not _only(order, {"expr", "order"}) or not _safe(order.expr, names=order_names):
                    return None
        # A chronological order is part of the series contract; GROUP BY alone
        # does not promise the same row order when its source changes.
        if len(original.order_by or []) != 1:
            return None
        ordered = original.order_by[0].expr
        if nested and isinstance(ordered, ast.Field) and len(ordered.chain) == 1:
            outer_aliases = {s.alias: s.expr for s in original.select if isinstance(s, ast.Alias)}
            ordered = outer_aliases.get(ordered.chain[0], ordered)
        if not _field(ordered, buckets[0]):
            return None
        predicates = []
        hours = None
        end_found = False
        for pred in inner.where.exprs if isinstance(inner.where, ast.And) else [inner.where]:
            if isinstance(pred, ast.CompareOperation) and _field(pred.left, "timestamp"):
                if pred.op == ast.CompareOperationOp.Lt and _anchor(pred.right) and not end_found:
                    end_found = True
                    continue
                rhs = pred.right
                if (
                    pred.op == ast.CompareOperationOp.GtEq
                    and isinstance(rhs, ast.ArithmeticOperation)
                    and rhs.op == ast.ArithmeticOperationOp.Sub
                    and _anchor(rhs.left)
                    and isinstance(rhs.right, ast.Call)
                    and rhs.right.name == "toIntervalHour"
                    and _only(rhs.right, {"name", "args"})
                    and len(rhs.right.args) == 1
                    and isinstance(rhs.right.args[0], ast.Constant)
                    and type(rhs.right.args[0].value) is int
                    and hours is None
                ):
                    hours = rhs.right.args[0].value
                    continue
            if pred is None or not _safe(pred, names={"person_id", "event", "properties"}):
                return None
            predicates.append(pred)
        if not end_found or hours is None or not 1 <= hours <= 24 * 366:
            return None
        local = now.astimezone(ZoneInfo(timezone))
        end = local.replace(minute=0, second=0, microsecond=0).astimezone(UTC)
        start = end - timedelta(hours=hours)
        # Reject fractional offsets and any offset change, including two transitions
        # within a long range. Daily UTC jobs must not bisect local hourly buckets.
        offsets = {(start + timedelta(hours=i)).astimezone(ZoneInfo(timezone)).utcoffset() for i in range(hours + 1)}
        if len(offsets) != 1 or any(o is None or o.total_seconds() % 3600 for o in offsets):
            return None
        metrics_by_key = {
            _key(n): n for n in _walk(inner.select) if isinstance(n, ast.Call) and n.name in {"uniq", "uniqIf"}
        }
        if not 1 <= len(metrics_by_key) <= 16:
            return None
        return HourlyUniqPlan(original, inner, list(metrics_by_key.values()), predicates, start, end, timezone, nested)
    except (BaseHogQLError, ValueError, KeyError):
        return None
