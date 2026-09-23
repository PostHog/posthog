"""Recognize the SQL detector queries whose history can be served from cached hourly buckets.

A detector scores the whole window of bucketed values on every check, but only a query whose
every bucket is computed from that bucket's own rows can have its older buckets reused. This
module proves that property, or refuses.

The matcher deliberately mirrors ``hogql_query_optimization`` in PR #102956, which narrows the
scan of eligible *threshold* last-row alerts. Both need the same proof; they differ in what they
do with it. Merge the two into one matcher once both have landed.
"""

from copy import deepcopy
from dataclasses import field, fields
from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS, LimitContext, get_default_limit_for_context
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_select

from posthog.dataclasses import frozen

# The result must hold every bucket of the window, or the series a full scan returns is a
# truncated prefix and the cached series would silently disagree with it. Reserve headroom for
# the extra buckets a timezone offset can add at the edges of the window.
_ROW_LIMIT_HEADROOM = 48
# Below this the window is too short for the narrowed scan to save anything.
_MIN_WINDOW_HOURS = 2

_RESERVED_ALIASES = {"timestamp", "event", "distinct_id", "person_id", "properties", "events"}
_ROW_LOCAL_FIELD_ROOTS = ("timestamp", "event", "distinct_id", "person_id", "properties")
# Deterministic scalar functions of the row alone — no clock, no randomness, no other rows.
_ROW_LOCAL_CALLS = (
    "toString",
    "toInt",
    "toFloat",
    "toIntOrNull",
    "toFloatOrNull",
    "lower",
    "upper",
    "coalesce",
    "ifNull",
    "trim",
)


@frozen
class _SeriesAliases:
    bucket: str
    value: str


@frozen
class _OuterShape:
    """A one-level projection over the aggregation: rename the bucket, combine the aggregates."""

    bucket_alias: str
    value_alias: str
    inner_bucket: str
    inner_fields: frozenset[str]


_SCALAR_CALLS = ("greatest", "least", "round", "abs", "coalesce", "if")


def _scalar_reads(expr: ast.Expr) -> frozenset[str] | None:
    """The inner aliases a deterministic per-row scalar expression reads, or None if it is not one."""
    if isinstance(expr, ast.Constant):
        return frozenset()
    if isinstance(expr, ast.Field):
        return frozenset({str(expr.chain[0])}) if len(expr.chain) == 1 else None
    if isinstance(expr, ast.ArithmeticOperation):
        left, right = _scalar_reads(expr.left), _scalar_reads(expr.right)
        return left | right if left is not None and right is not None else None
    if isinstance(expr, ast.CompareOperation):
        left, right = _scalar_reads(expr.left), _scalar_reads(expr.right)
        return left | right if left is not None and right is not None else None
    if isinstance(expr, ast.Call) and expr.name in _SCALAR_CALLS and not expr.params and not expr.distinct:
        reads: frozenset[str] = frozenset()
        for arg in expr.args:
            found = _scalar_reads(arg)
            if found is None:
                return None
            reads |= found
        return reads
    return None


def _match_outer(query: ast.SelectQuery, column: str | None) -> _OuterShape | None:
    """Recognize ``SELECT <bucket>, <scalar over aggregates> FROM (...) ORDER BY <bucket> ASC``."""
    allowed = {"start", "end", "type", "select", "select_from", "order_by", "limit"}
    if any(getattr(query, field_.name) for field_ in fields(query) if field_.name not in allowed):
        return None
    source = query.select_from
    if source is None or not isinstance(source.table, ast.SelectQuery):
        return None
    if any(
        getattr(source, field_.name)
        for field_ in fields(source)
        if field_.name not in {"start", "end", "type", "table", "alias"}
    ):
        return None
    if len(query.select) != 2 or not all(isinstance(expr, ast.Alias) for expr in query.select):
        return None
    bucket, value = query.select
    assert isinstance(bucket, ast.Alias) and isinstance(value, ast.Alias)
    if bucket.alias in _RESERVED_ALIASES or value.alias in _RESERVED_ALIASES or bucket.alias == value.alias:
        return None
    if column is not None and value.alias != column:
        return None
    if not isinstance(bucket.expr, ast.Field) or len(bucket.expr.chain) != 1:
        return None
    reads = _scalar_reads(value.expr)
    if not reads:
        return None
    if not query.order_by or len(query.order_by) != 1:
        return None
    order = query.order_by[0]
    if (
        order.order != "ASC"
        or order.with_fill
        or not isinstance(order.expr, ast.Field)
        or order.expr.chain != [bucket.alias]
    ):
        return None
    return _OuterShape(
        bucket_alias=bucket.alias,
        value_alias=value.alias,
        inner_bucket=str(bucket.expr.chain[0]),
        inner_fields=reads,
    )


@frozen
class _HourlySeriesShape:
    window_hours: int
    bucket_alias: str
    value_alias: str


class _HourlySeriesMatcher:
    """Decide whether one parsed query is a bucket-local hourly aggregation.

    With ``outer`` set, ``query`` is the inner aggregation of a recognized one-level projection:
    its select may carry several aggregates for the projection to combine, the projection owns
    ordering and the limit, and the output column names are the projection's.
    """

    def __init__(
        self,
        query: ast.SelectQuery,
        column: str | None,
        outer: _OuterShape | None = None,
        explicit_limit: ast.Expr | None = None,
    ) -> None:
        self.outer = outer
        self.explicit_limit = explicit_limit
        self.query = query
        self.column = column

    @staticmethod
    def _plain_call(expr: ast.Expr, name: str) -> bool:
        return (
            isinstance(expr, ast.Call)
            and expr.name == name
            and not any((expr.params, expr.distinct, expr.within_group, expr.order_by, expr.filter_expr))
        )

    @staticmethod
    def _timestamp(expr: ast.Expr) -> bool:
        return isinstance(expr, ast.Field) and expr.chain == ["timestamp"]

    def _bucket(self, expr: ast.Expr) -> bool:
        return (
            isinstance(expr, ast.Call)
            and self._plain_call(expr, "toStartOfHour")
            and len(expr.args) == 1
            and self._timestamp(expr.args[0])
        )

    def _end(self, expr: ast.Expr) -> bool:
        return (
            self._plain_call(expr, "toStartOfHour")
            and isinstance(expr, ast.Call)
            and len(expr.args) == 1
            and self._plain_call(expr.args[0], "now")
            and isinstance(expr.args[0], ast.Call)
            and not expr.args[0].args
        )

    def _row_local(self, expr: ast.Expr) -> bool:
        """True when the predicate reads only the row itself — never the clock.

        The two window bounds are the only now()-dependent predicates the cache can account for,
        and ``_window_hours`` recognizes those structurally before this check runs. Any other
        now()-dependent predicate changes which rows count toward a bucket as the bucket ages, so
        its value would depend on when it was computed.
        """
        if isinstance(expr, ast.Constant):
            return True
        if isinstance(expr, ast.Field):
            return bool(expr.chain) and expr.chain[0] in _ROW_LOCAL_FIELD_ROOTS
        if isinstance(expr, ast.CompareOperation):
            return (
                expr.op
                in (
                    ast.CompareOperationOp.Eq,
                    ast.CompareOperationOp.NotEq,
                    ast.CompareOperationOp.Gt,
                    ast.CompareOperationOp.GtEq,
                    ast.CompareOperationOp.Lt,
                    ast.CompareOperationOp.LtEq,
                    ast.CompareOperationOp.In,
                    ast.CompareOperationOp.NotIn,
                )
                and self._row_local(expr.left)
                and self._row_local(expr.right)
            )
        if isinstance(expr, ast.And | ast.Or):
            return all(self._row_local(part) for part in expr.exprs)
        if isinstance(expr, ast.Not):
            return self._row_local(expr.expr)
        if isinstance(expr, ast.Tuple):
            return all(self._row_local(part) for part in expr.exprs)
        if isinstance(expr, ast.Call) and expr.name in _ROW_LOCAL_CALLS and not expr.params and not expr.distinct:
            return all(self._row_local(arg) for arg in expr.args)
        return False

    def _hours(self, expr: ast.Expr) -> int | None:
        if (
            isinstance(expr, ast.Call)
            and self._plain_call(expr, "toIntervalHour")
            and len(expr.args) == 1
            and isinstance(expr.args[0], ast.Constant)
            and type(expr.args[0].value) is int
        ):
            return expr.args[0].value
        return None

    def _aggregate(self, expr: ast.Expr) -> bool:
        if isinstance(expr, ast.ArithmeticOperation) and expr.op in (
            ast.ArithmeticOperationOp.Add,
            ast.ArithmeticOperationOp.Sub,
        ):
            return self._aggregate(expr.left) and self._aggregate(expr.right)
        if not isinstance(expr, ast.Call) or not self._plain_call(expr, expr.name):
            return False
        if expr.name == "count":
            return not expr.args
        if expr.name == "countIf":
            return len(expr.args) == 1 and self._row_local(expr.args[0])
        if expr.name in ("uniq", "uniqExact", "uniqIf", "uniqExactIf"):
            return len(expr.args) == (2 if expr.name.endswith("If") else 1) and all(
                self._row_local(arg) for arg in expr.args
            )
        return False

    def _aliases(self) -> "_SeriesAliases | None":
        """The (bucket, value) output column names, when the shape allows reusing older buckets."""
        query = self.query
        # Fail closed for new clauses, as well as windows, joins, fill, CTEs and HAVING. Those can
        # make one bucket depend on rows outside it. The inner query of a projection owns neither
        # ordering nor the limit — an inner LIMIT without ORDER BY would make the rows arbitrary.
        allowed = {"start", "end", "type", "select", "select_from", "where", "group_by"}
        if self.outer is None:
            allowed = allowed | {"order_by", "limit"}
        if any(getattr(query, field_.name) for field_ in fields(query) if field_.name not in allowed):
            return None
        source = query.select_from
        if not source or not isinstance(source.table, ast.Field) or source.table.chain != ["events"]:
            return None
        if any(
            getattr(source, field_.name)
            for field_ in fields(source)
            if field_.name not in {"start", "end", "type", "table"}
        ):
            return None
        if len(query.select) < 2 or not all(isinstance(expr, ast.Alias) for expr in query.select):
            return None
        if self.outer is None and len(query.select) != 2:
            return None
        buckets = [expr for expr in query.select if isinstance(expr, ast.Alias) and self._bucket(expr.expr)]
        aggregates = [expr for expr in query.select if isinstance(expr, ast.Alias) and not self._bucket(expr.expr)]
        if len(buckets) != 1:
            return None
        bucket = buckets[0]
        names = {expr.alias for expr in query.select if isinstance(expr, ast.Alias)}
        if len(names) != len(query.select) or names & _RESERVED_ALIASES:
            return None
        if not all(self._aggregate(value.expr) for value in aggregates):
            return None
        if self.outer is not None:
            if bucket.alias != self.outer.inner_bucket:
                return None
            if not self.outer.inner_fields <= {value.alias for value in aggregates}:
                return None
            value_alias = self.outer.value_alias
        else:
            # An explicit column must name the aggregate. Without one the extractor picks the
            # single numeric column, which in this two-column shape is the aggregate either way.
            value_alias = aggregates[0].alias
            if self.column is not None and value_alias != self.column:
                return None
        if not query.group_by or len(query.group_by) != 1:
            return None
        group = query.group_by[0]
        if not isinstance(group, ast.Field) or group.chain != [bucket.alias]:
            return None
        if self.outer is None:
            if not query.order_by or len(query.order_by) != 1:
                return None
            order = query.order_by[0]
            if (
                order.order != "ASC"
                or order.with_fill
                or not isinstance(order.expr, ast.Field)
                or order.expr.chain != [bucket.alias]
            ):
                return None
            bucket_alias = bucket.alias
        else:
            bucket_alias = self.outer.bucket_alias
        return _SeriesAliases(bucket=bucket_alias, value=value_alias)

    def _lower_bound_hours(self, predicate: ast.Expr) -> int | None:
        """The N of a ``timestamp >= toStartOfHour(now()) - INTERVAL N HOUR`` conjunct, else None."""
        if not isinstance(predicate, ast.CompareOperation) or not self._timestamp(predicate.left):
            return None
        lower = predicate.right
        if (
            predicate.op == ast.CompareOperationOp.GtEq
            and isinstance(lower, ast.ArithmeticOperation)
            and lower.op == ast.ArithmeticOperationOp.Sub
            and self._end(lower.left)
        ):
            return self._hours(lower.right)
        return None

    def _is_end_bound(self, predicate: ast.Expr) -> bool:
        return (
            isinstance(predicate, ast.CompareOperation)
            and predicate.op == ast.CompareOperationOp.Lt
            and self._timestamp(predicate.left)
            and self._end(predicate.right)
        )

    def _window_hours(self) -> int | None:
        """The number of hourly buckets the query asks for, when its bounds pin one.

        Every top-level conjunct must be one of the two exact bound shapes or contain no clock at
        all. A now()-dependent predicate in any other shape shifts which rows a bucket holds as
        time advances without moving the window this returns, so the cache would keep buckets a
        full scan no longer reads.

        The window must fit under the limit the query really runs with — the author's explicit
        LIMIT, or the context default — because the full scan the cache is compared against would
        otherwise come back truncated.
        """
        query = self.query
        if not isinstance(query.where, ast.And):
            return None
        row_limit = get_default_limit_for_context(LimitContext.QUERY_ASYNC)
        if self.explicit_limit is not None:
            if (
                not isinstance(self.explicit_limit, ast.Constant)
                or type(self.explicit_limit.value) is not int
                or self.explicit_limit.value <= 0
            ):
                return None
            row_limit = min(self.explicit_limit.value, MAX_SELECT_RETURNED_ROWS)
        hours: int | None = None
        has_end = False
        for predicate in query.where.exprs:
            if self._is_end_bound(predicate):
                has_end = True
                continue
            found = self._lower_bound_hours(predicate)
            if found is not None:
                # A second lower bound narrows the window further, so keep the tightest.
                hours = found if hours is None else min(hours, found)
                continue
            if not self._row_local(predicate):
                return None
        if not has_end or hours is None:
            return None
        if not _MIN_WINDOW_HOURS < hours < row_limit - _ROW_LIMIT_HEADROOM:
            return None
        return hours

    def match(self) -> _HourlySeriesShape | None:
        aliases = self._aliases()
        if aliases is None:
            return None
        hours = self._window_hours()
        if hours is None:
            return None
        return _HourlySeriesShape(window_hours=hours, bucket_alias=aliases.bucket, value_alias=aliases.value)


@frozen
class DetectorSeriesQuery:
    """A SQL detector query proven to produce one value per hour from that hour's own rows.

    ``window_hours`` is read from the query's own bounds, so the cache follows whatever window the
    user wrote rather than a setting of ours.
    """

    window_hours: int
    bucket_alias: str
    value_alias: str
    source: dict = field(repr=False)
    parsed: ast.SelectQuery = field(repr=False)

    @property
    def column_names(self) -> list[str]:
        return [self.bucket_alias, self.value_alias]

    def prepared(self, *, at: datetime, tz: str) -> dict:
        """The full query with its clock pinned, for the rebuild scan."""
        return self._override(deepcopy(self.parsed), at=at, tz=tz)

    def narrowed_to(self, hours: int, *, at: datetime, tz: str) -> dict:
        """The same query, reading only the most recent ``hours`` buckets, anchored at ``at``.

        The added bound sits alongside the original one and is never wider, so the rows it keeps
        are a suffix of the rows the original query would have grouped.
        """
        if hours >= self.window_hours:
            raise ValueError(f"narrowing to {hours}h would not shorten a {self.window_hours}h window")
        narrowed = deepcopy(self.parsed)
        events_query = narrowed
        if narrowed.select_from is not None and isinstance(narrowed.select_from.table, ast.SelectQuery):
            events_query = narrowed.select_from.table
        assert isinstance(events_query.where, ast.And)
        events_query.where.exprs.append(
            ast.CompareOperation(
                left=ast.Field(chain=["timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.ArithmeticOperation(
                    left=ast.Call(name="toStartOfHour", args=[ast.Call(name="now", args=[])]),
                    op=ast.ArithmeticOperationOp.Sub,
                    right=ast.Call(name="toIntervalHour", args=[ast.Constant(value=hours)]),
                ),
            )
        )
        return self._override(narrowed, at=at, tz=tz)

    def _override(self, tree: ast.SelectQuery, *, at: datetime, tz: str) -> dict:
        """Pin the clock and wrap the tree as a query override.

        Pinning replaces every ``now()`` with ``at`` rendered in the team timezone, so the
        warehouse evaluates the bounds the caller reasoned about — a warehouse clock that crosses
        an hour boundary mid-check cannot shift the scan against the cache bookkeeping.
        """
        _pin_clock(tree, at=at, tz=tz)
        override = deepcopy(self.source)
        target = override["source"] if override.get("kind") == "DataVisualizationNode" else override
        target["query"] = tree.to_hogql()
        return override


def _pin_clock(node: ast.AST, *, at: datetime, tz: str) -> None:
    """Replace every ``now()`` under ``node`` with ``at`` as an epoch literal in timezone ``tz``.

    The matcher only admits ``now()`` inside the recognized window bounds, so this touches
    nothing else.
    """
    # Epoch seconds, not a wall-clock string: during a DST fold the same local time names two
    # instants, and a string rendering would resolve to the wrong one for a whole hour.
    pinned = ast.Call(
        name="toTimeZone",
        args=[
            ast.Call(name="fromUnixTimestamp", args=[ast.Constant(value=int(at.timestamp()))]),
            ast.Constant(value=tz),
        ],
    )
    for field_ in fields(node):
        value = getattr(node, field_.name)
        if isinstance(value, ast.Call) and value.name == "now" and not value.args:
            setattr(node, field_.name, deepcopy(pinned))
        elif isinstance(value, ast.AST):
            _pin_clock(value, at=at, tz=tz)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, ast.Call) and item.name == "now" and not item.args:
                    value[index] = deepcopy(pinned)
                elif isinstance(item, ast.AST):
                    _pin_clock(item, at=at, tz=tz)


def match_detector_series_query(query: object, *, column: str | None) -> DetectorSeriesQuery | None:
    """Recognize an insight query whose detector history can come from cached buckets, or None."""
    if not isinstance(query, dict):
        return None
    source = query.get("source") if query.get("kind") == "DataVisualizationNode" else query
    if not isinstance(source, dict) or source.get("kind") != "HogQLQuery" or not isinstance(source.get("query"), str):
        return None
    if source.get("connectionId") or source.get("sendRawQuery") or source.get("explain"):
        return None
    try:
        parsed = parse_select(source["query"])
    except BaseHogQLError:
        # Let the normal query execution report invalid or unsupported HogQL.
        return None
    if not isinstance(parsed, ast.SelectQuery):
        return None
    if parsed.select_from is not None and isinstance(parsed.select_from.table, ast.SelectQuery):
        outer = _match_outer(parsed, column)
        if outer is None:
            return None
        matched = _HourlySeriesMatcher(
            parsed.select_from.table, column, outer=outer, explicit_limit=parsed.limit
        ).match()
    else:
        matched = _HourlySeriesMatcher(parsed, column, explicit_limit=parsed.limit).match()
    if matched is None:
        return None
    return DetectorSeriesQuery(
        window_hours=matched.window_hours,
        bucket_alias=matched.bucket_alias,
        value_alias=matched.value_alias,
        source=query,
        parsed=parsed,
    )
