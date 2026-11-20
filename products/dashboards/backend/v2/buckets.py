"""Bucketed HogQL for `dashboard-v2`: a query's finished time buckets are kept once and reused by any range.

A HogQL target marked `bucketed` returns its time bucket as its first column, filters time only through `{filters}`,
and aggregates only within a bucket. Each bucket then depends on its own rows alone, so a finished bucket is stored
once in the query cache's Valkey, keyed by the query without its date range. Any range is the stored buckets plus
ClickHouse runs for the missing spans and for the newest buckets, which can still receive rows.
"""

import json
import random
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import BoundedSemaphore
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from django.conf import settings

import zstd
import orjson
import structlog
from prometheus_client import Counter

from posthog.hogql import ast
from posthog.hogql.functions.aggregations import HOGQL_AGGREGATIONS
from posthog.hogql.parser import parse_select
from posthog.hogql.visitor import TraversingVisitor, clear_locations

from posthog.dataclasses import frozen
from posthog.query_cache import storage
from posthog.query_cache.read_history import HISTORY_DAYS
from posthog.renderers import SafeJSONRenderer

logger = structlog.get_logger(__name__)

# Kept as long as the store is read or written within this, like the read history that decides warming.
STORE_TTL = timedelta(days=HISTORY_DAYS + 1)
# Events still arrive for a while after a bucket ends: hourly buckets move up to 19% in the first minutes after
# they close and under 1% an hour later. Logs and metrics land within minutes.
EVENTS_SETTLE = timedelta(hours=1)
FAST_SETTLE = timedelta(minutes=15)
_FAST_SETTLE_TABLES = frozenset({"logs", "log_attributes", "metrics"})
# A range with more buckets than this runs whole: reading that many fields costs more than it saves.
MAX_BUCKETS_PER_RANGE = 5000
# A store with more buckets or bytes than this starts over on its next write.
MAX_STORED_BUCKETS = 20_000
MAX_STORE_BYTES = 16 * 1024 * 1024
# A store older than this starts over, so deleted events and the retention floor reach its buckets.
MAX_STORE_AGE = STORE_TTL
# One answer stops splitting dense spans past this many ClickHouse runs or rows read, and runs whole instead.
MAX_SPAN_RUNS = 32
MAX_FETCHED_ROWS = 100_000
# What `{filters}` prints for a range with no end. ClickHouse dates stop at 2299.
UNBOUNDED_RANGE_END = datetime(2200, 1, 1, tzinfo=UTC)
_META = "meta"
_KEY_PREFIX = "dashboards_v2_buckets"

BUCKETED_RUNS = Counter(
    "posthog_dashboard_v2_bucketed_runs_total",
    "Bucketed HogQL runs of dashboard-v2 query batches, by outcome.",
    labelnames=["outcome"],
)
SHADOW_CHECKS = Counter(
    "posthog_dashboard_v2_bucketed_shadow_checks_total",
    "Sampled comparisons of a bucket-assembled answer with a whole-range run, by outcome.",
    labelnames=["outcome"],
)


class NotBucketable(Exception):
    """The query does not meet the bucketed contract. The message says why, for the panel's provenance."""


class BucketContractError(Exception):
    """A run returned rows the contract does not allow, such as a first column off the bucket grid."""


class BucketStoreError(BucketContractError):
    """The store could not be read, so the query runs whole."""


# Bucket functions and the grid each makes.
_BUCKET_FUNCTIONS: dict[str, tuple[str, int]] = {
    "toStartOfMinute": ("minute", 1),
    "toStartOfFiveMinutes": ("minute", 5),
    "toStartOfTenMinutes": ("minute", 10),
    "toStartOfFifteenMinutes": ("minute", 15),
    "toStartOfHour": ("hour", 1),
    "toStartOfDay": ("day", 1),
}
_INTERVAL_FUNCTIONS = {"toIntervalMinute": "minute", "toIntervalHour": "hour", "toIntervalDay": "day"}
_CLOCK_FUNCTIONS = frozenset(
    {"now", "now64", "today", "yesterday", "currenttimestamp", "current_timestamp", "current_date", "nowinblock"}
)
_ACTIVITY_LOGS_TABLE = "system.activity_logs"


@frozen
class BucketGrid:
    """Where a bucket function starts its buckets, in the project's timezone. Minute grids divide an hour and hour
    and day grids are one unit, so local starts of hours and days are always bucket starts."""

    unit: Literal["minute", "hour", "day"]
    size: int
    tz: ZoneInfo

    @property
    def step(self) -> timedelta:
        return {"minute": timedelta(minutes=self.size), "hour": timedelta(hours=1), "day": timedelta(days=1)}[self.unit]

    def floor(self, t: datetime) -> datetime:
        local = t.astimezone(self.tz)
        if self.unit == "minute":
            local = local.replace(minute=local.minute - local.minute % self.size, second=0, microsecond=0)
        elif self.unit == "hour":
            local = local.replace(minute=0, second=0, microsecond=0)
        else:
            local = local.replace(hour=0, minute=0, second=0, microsecond=0, fold=0)
        return local.astimezone(UTC)

    def next(self, bucket: datetime) -> datetime:
        # A local day is 23 to 25 hours long, so two hours past a day's length always lands in the next one.
        slack = timedelta(hours=2) if self.unit == "day" else timedelta(0)
        after = self.floor(bucket + self.step + slack)
        if after <= bucket:
            raise BucketContractError(f"the bucket grid does not advance past {bucket.isoformat()}")
        return after

    def is_start(self, t: datetime) -> bool:
        return self.floor(t) == t

    def ceil(self, t: datetime) -> datetime:
        return t if self.is_start(t) else self.next(self.floor(t))

    def starts(self, start: datetime, end: datetime) -> list[datetime]:
        """Bucket starts in [start, end), where start is a bucket start."""
        out: list[datetime] = []
        bucket = start
        while bucket < end:
            out.append(bucket)
            bucket = self.next(bucket)
        return out


@frozen
class BucketedQuery:
    """What the contract check learned about a bucketed query."""

    unit: Literal["minute", "hour", "day"]
    size: int
    settle: timedelta
    # The direction of an ORDER BY that starts with the bucket, or None without an ORDER BY.
    order: Optional[Literal["ASC", "DESC"]]
    limit: Optional[int]

    def grid(self, tz: ZoneInfo) -> BucketGrid:
        return BucketGrid(unit=self.unit, size=self.size, tz=tz)


class _Scan(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.window = False
        self.clock = False
        self.nested_dates = False
        self.compare = False
        self.top_aggregate = False
        self.top_date_filter: set[str] = set()
        self.dates_outside_where = False
        self.tables: set[str] = set()
        self._in_top_where = False
        self._top_where_placeholders: set[int] = set()

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.depth += 1
        try:
            if self.depth == 1:
                for clause in (node.where, node.prewhere):
                    if clause is not None:
                        self._in_top_where = True
                        try:
                            self.visit(clause)
                        finally:
                            self._in_top_where = False
            super().visit_select_query(node)
        finally:
            self.depth -= 1

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.window = True
        super().visit_window_function(node)

    def visit_call(self, node: ast.Call) -> None:
        if node.name.lower() in _CLOCK_FUNCTIONS:
            self.clock = True
        if self.depth == 1 and node.name in HOGQL_AGGREGATIONS:
            self.top_aggregate = True
        super().visit_call(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field):
            self.tables.add(".".join(str(part) for part in node.table.chain))
        super().visit_join_expr(node)

    def visit_placeholder(self, node: ast.Placeholder) -> None:
        chain = node.chain
        call = node.expr
        if chain is None and isinstance(call, ast.ExprCall) and isinstance(call.expr, ast.Field):
            chain = call.expr.chain
        if chain is None and isinstance(call, ast.Call) and call.name == "filters":
            chain = ["filters", "bound"]
        if chain and chain[0] == "filters":
            if "previous" in chain or "compareDate" in chain:
                self.compare = True
            if self.depth > 1:
                self.nested_dates = True
            elif self._in_top_where:
                self.top_date_filter.add(".".join(str(part) for part in chain))
                self._top_where_placeholders.add(id(node))
            elif id(node) not in self._top_where_placeholders:
                self.dates_outside_where = True
        super().visit_placeholder(node)


def _unalias(expr: ast.Expr) -> ast.Expr:
    while isinstance(expr, ast.Alias):
        expr = expr.expr
    return expr


def _bucket_grid(expr: ast.Expr) -> Optional[tuple[str, int]]:
    expr = _unalias(expr)
    if not isinstance(expr, ast.Call) or not expr.args:
        return None
    column = expr.args[0]
    if not (isinstance(column, ast.Field) and column.chain[-1] == "timestamp"):
        return None
    if expr.name in _BUCKET_FUNCTIONS and len(expr.args) == 1:
        return _BUCKET_FUNCTIONS[expr.name]
    if expr.name == "toStartOfInterval" and len(expr.args) == 2:
        interval = expr.args[1]
        if (
            isinstance(interval, ast.Call)
            and interval.name in _INTERVAL_FUNCTIONS
            and len(interval.args) == 1
            and isinstance(interval.args[0], ast.Constant)
            and isinstance(interval.args[0].value, int)
        ):
            unit, size = _INTERVAL_FUNCTIONS[interval.name], interval.args[0].value
            if (unit == "minute" and size > 0 and 60 % size == 0) or (unit != "minute" and size == 1):
                return unit, size
    return None


def _refers_to_bucket(expr: ast.Expr, bucket: ast.Expr) -> bool:
    if isinstance(expr, ast.Constant) and expr.value == 1:
        return True
    if isinstance(expr, ast.PositionalRef) and expr.index == 1:
        return True
    if isinstance(bucket, ast.Alias) and isinstance(expr, ast.Field) and expr.chain == [bucket.alias]:
        return True
    return clear_locations(_unalias(expr)) == clear_locations(_unalias(bucket))


def check_bucketed(query: str) -> BucketedQuery:
    """The query's bucket grid and settle time, or NotBucketable saying what breaks the contract.
    A port of Dash's `whyNotBucketed`, on the parsed query rather than its text."""
    try:
        node = parse_select(query)
    except Exception:
        raise NotBucketable("HogQL is kept per bucket only once it parses")
    if not isinstance(node, ast.SelectQuery):
        raise NotBucketable("HogQL is kept per bucket when it is one SELECT; here it combines several (UNION)")

    problems: list[str] = []
    scan = _Scan()
    scan.visit(node)
    bucket = node.select[0] if node.select else None
    grid = _bucket_grid(bucket) if bucket is not None else None
    if grid is None:
        problems.append(
            "its first column is not the bucket: toStartOfHour(timestamp), toStartOfDay(timestamp), "
            "toStartOfMinute(timestamp) or toStartOfInterval(timestamp, INTERVAL n MINUTE) with n dividing an hour"
        )
    if not (
        {"filters"} <= scan.top_date_filter
        or {"filters.dateRange.from", "filters.dateRange.to"} <= scan.top_date_filter
    ):
        problems.append("it does not filter time with {filters} in its WHERE")
    if scan.window:
        problems.append("a window function (OVER …) reads across buckets")
    if scan.clock:
        problems.append("it reads the clock (now(), today()), so a stored bucket would go stale")
    if scan.nested_dates:
        problems.append("a subquery reads the date range, so it can aggregate across buckets")
    if scan.dates_outside_where:
        problems.append("it reads the date range outside its WHERE, so each run would see different bounds")
    if scan.compare:
        problems.append("it compares with a previous period")
    if _ACTIVITY_LOGS_TABLE in scan.tables:
        problems.append("activity log access rules move with the clock")
    if bucket is not None and grid is not None:
        if node.group_by_mode:
            problems.append("ROLLUP, CUBE and GROUPING SETS add rows across buckets")
        if node.group_by and not any(_refers_to_bucket(expr, bucket) for expr in node.group_by):
            problems.append("it does not GROUP BY the bucket")
        if not node.group_by and scan.top_aggregate:
            problems.append("it aggregates the whole range without a GROUP BY on the bucket")
    if node.limit_by is not None or node.offset is not None or node.limit_with_ties or node.limit_percent:
        problems.append("OFFSET, LIMIT BY and WITH TIES pick rows across buckets")
    limit: Optional[int] = None
    if node.limit is not None:
        if isinstance(node.limit, ast.Constant) and isinstance(node.limit.value, int):
            limit = node.limit.value
        else:
            problems.append("its LIMIT is not a number")
    order: Optional[Literal["ASC", "DESC"]] = None
    if node.order_by:
        if bucket is not None and _refers_to_bucket(node.order_by[0].expr, bucket):
            order = node.order_by[0].order
        else:
            problems.append("its ORDER BY does not start with the bucket")
    if problems or grid is None:
        raise NotBucketable(
            f"HogQL is kept per bucket when it returns one row set per time bucket; here {'; '.join(problems)}"
        )
    fast = bool(scan.tables) and scan.tables <= _FAST_SETTLE_TABLES
    unit, size = grid
    return BucketedQuery(
        unit=unit,  # type: ignore[arg-type]
        size=size,
        settle=FAST_SETTLE if fast else EVENTS_SETTLE,
        order=order,
        limit=limit,
    )


@frozen
class SpanRows:
    """A run of the query over [start, end)."""

    columns: list[Any]
    types: list[Any]
    rows: list[list[Any]]
    has_more: bool


@frozen
class StoreMeta:
    """The stretch of buckets the store holds: every bucket in [start, end) is stored, or had no rows."""

    start: datetime
    end: datetime
    columns: list[Any]
    types: list[Any]
    # When the store started over, and the compressed bytes of its buckets.
    born: datetime
    size: int

    def encode(self) -> bytes:
        return orjson.dumps(
            {
                "from": int(self.start.timestamp()),
                "to": int(self.end.timestamp()),
                "columns": self.columns,
                "types": self.types,
                "born": int(self.born.timestamp()),
                "bytes": self.size,
            }
        )

    @staticmethod
    def decode(raw: bytes) -> Optional["StoreMeta"]:
        try:
            data = orjson.loads(raw)
            return StoreMeta(
                start=datetime.fromtimestamp(data["from"], UTC),
                end=datetime.fromtimestamp(data["to"], UTC),
                columns=data["columns"],
                types=data["types"],
                born=datetime.fromtimestamp(data["born"], UTC),
                size=int(data["bytes"]),
            )
        except (ValueError, KeyError, TypeError):
            return None


# Writes only if the stretch is still what this run read, so two runs extending one store never leave it
# claiming buckets neither wrote. ARGV: expected meta ("" for none), new meta, TTL seconds, reset, field/value pairs.
_WRITE_SCRIPT = """
local current = redis.call('HGET', KEYS[1], 'meta') or ''
if current ~= ARGV[1] then
  return 0
end
if ARGV[4] == '1' then
  redis.call('DEL', KEYS[1])
end
for i = 5, #ARGV, 2 do
  redis.call('HSET', KEYS[1], ARGV[i], ARGV[i + 1])
end
redis.call('HSET', KEYS[1], 'meta', ARGV[2])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return 1
"""


def store_key(team_id: int, range_free_cache_key: str, grid: BucketGrid) -> str:
    """One store per query and bucket size. `range_free_cache_key` is the query's cache key planned without a date
    range, so it carries everything else that changes the answer: the team, timezone, modifiers, variables and the
    user's access restrictions."""
    identity = sha256(f"{range_free_cache_key}|{grid.unit}|{grid.size}".encode()).hexdigest()[:32]
    return f"{_KEY_PREFIX}:{team_id}:{identity}"


def _field(bucket: datetime) -> str:
    return str(int(bucket.timestamp()))


def pack(rows: list[list[Any]]) -> bytes:
    return zstd.compress(SafeJSONRenderer().render(rows))


class BucketStore:
    """A Valkey hash: field `meta` holds the stored stretch and the columns, and one field per bucket start (epoch
    seconds) holds that bucket's rows as zstd-compressed JSON. Buckets with no rows have no field. Each method raises
    BucketStoreError when Valkey or a stored value fails."""

    def __init__(self, key: str) -> None:
        self.key = key

    def read_meta(self) -> tuple[bytes, Optional[StoreMeta]]:
        try:
            raw = storage.query_cache_read_client().hget(self.key, _META)
        except Exception as e:
            raise BucketStoreError("the store could not be read") from e
        if not raw:
            return b"", None
        return raw, StoreMeta.decode(raw)

    def read(self, buckets: Sequence[datetime]) -> tuple[Optional[StoreMeta], dict[datetime, list[list[Any]]]]:
        """The stretch the store holds now, read with the buckets so a store that expired meanwhile shows."""
        try:
            raw, *values = storage.query_cache_read_client().hmget(
                self.key, [_META, *(_field(bucket) for bucket in buckets)]
            )
            rows = {bucket: orjson.loads(zstd.decompress(value)) for bucket, value in zip(buckets, values) if value}
        except Exception as e:
            raise BucketStoreError("the store could not be read") from e
        return (StoreMeta.decode(raw) if raw else None), rows

    def write(self, *, expected: bytes, meta: StoreMeta, buckets: dict[datetime, bytes], reset: bool) -> bool:
        """`buckets` holds each bucket's rows as `pack` makes them."""
        args: list[Any] = [expected, meta.encode(), int(STORE_TTL.total_seconds()), "1" if reset else "0"]
        for bucket, packed in buckets.items():
            args.extend([_field(bucket), packed])
        try:
            # redis-py's stubs omit eval on RedisCluster; the runtime supports it for a single key.
            client = storage.query_cache_raw_client()
            return bool(client.eval(_WRITE_SCRIPT, 1, self.key, *args))  # type: ignore[union-attr]
        except Exception as e:
            raise BucketStoreError("the store could not be written") from e

    def size(self) -> int:
        try:
            return int(storage.query_cache_read_client().hlen(self.key))
        except Exception as e:
            raise BucketStoreError("the store could not be read") from e

    def touch(self) -> None:
        try:
            storage.query_cache_raw_client().expire(self.key, int(STORE_TTL.total_seconds()))
        except Exception as e:
            raise BucketStoreError("the store could not be written") from e


@frozen
class Part:
    start: datetime
    end: datetime
    source: Literal["store", "clickhouse"]


@frozen
class BucketedAnswer:
    columns: list[Any]
    types: list[Any]
    rows: list[list[Any]]
    has_more: bool
    parts: list[Part]
    stored_buckets: int
    # True when the store was too far from this range to extend, so nothing was read from it or written to it.
    far: bool = False


def _json_rows(rows: list[list[Any]]) -> list[list[Any]]:
    # As the batch renders results, so stored and freshly fetched rows read the same.
    return orjson.loads(SafeJSONRenderer().render(rows))


def _bucket_of(value: Any, tz: ZoneInfo) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise BucketContractError(f"the first column must be the bucket, got {value!r}")
    if not isinstance(value, datetime):
        raise BucketContractError(f"the first column must be the bucket, got {value!r}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return value.astimezone(UTC)


class _Runs:
    """The ClickHouse runs of one answer. A run that returns `row_cap` rows counts as cut short, because a query with
    its own LIMIT reports no hasMore. Past MAX_SPAN_RUNS runs or MAX_FETCHED_ROWS rows the query runs whole."""

    def __init__(self, fetch: Callable[[datetime, datetime], SpanRows], row_cap: Optional[int]) -> None:
        self._fetch = fetch
        self._row_cap = row_cap
        self._runs_left = MAX_SPAN_RUNS
        self._rows_left = MAX_FETCHED_ROWS

    def __call__(self, start: datetime, end: datetime) -> SpanRows:
        if self._runs_left <= 0:
            raise NotBucketable(f"keeping its buckets whole takes more than {MAX_SPAN_RUNS} runs")
        self._runs_left -= 1
        got = self._fetch(start, end)
        self._rows_left -= len(got.rows)
        if self._rows_left < 0:
            raise NotBucketable(f"keeping its buckets whole reads more than {MAX_FETCHED_ROWS} rows")
        if self._row_cap is not None and len(got.rows) >= self._row_cap:
            return SpanRows(columns=got.columns, types=got.types, rows=got.rows, has_more=True)
        return got


def _fetch_split(
    fetch: Callable[[datetime, datetime], SpanRows], grid: BucketGrid, start: datetime, end: datetime, now: datetime
) -> SpanRows:
    """One span, split in halves on the bucket grid when a run reaches the row limit, so no bucket is cut short."""
    got = fetch(start, end)
    if not got.has_more:
        return got
    first = grid.ceil(start)
    if grid.next(first) >= end:
        raise BucketContractError("one bucket has more rows than the row limit: use a smaller bucket or fewer series")
    # A range with no end runs to UNBOUNDED_RANGE_END, but its rows are before now: split there first.
    pivot = grid.ceil(now)
    if first < pivot < end and end - pivot > pivot - start:
        middle = pivot
    else:
        middle = max(grid.floor(first + (end - first) / 2), grid.next(first))
    left = _fetch_split(fetch, grid, start, middle, now)
    right = _fetch_split(fetch, grid, middle, end, now)
    return SpanRows(columns=right.columns, types=right.types, rows=[*left.rows, *right.rows], has_more=False)


@frozen
class Span:
    """[start, end)."""

    start: datetime
    end: datetime

    @property
    def empty(self) -> bool:
        return self.start >= self.end

    def contains(self, other: "Span") -> bool:
        return self.start <= other.start and other.end <= self.end


def _merge_spans(spans: Iterable[Span], cuts: set[datetime]) -> list[Span]:
    """Merge overlapping or touching spans, unless a merge would put a cut inside one span. A cut is a range end
    that is not a bucket start: the bucket around it must be run up to the cut and no further."""
    merged: list[Span] = []
    for span in sorted((span for span in spans if not span.empty), key=lambda span: (span.start, span.end)):
        if merged:
            joined = Span(start=merged[-1].start, end=max(merged[-1].end, span.end))
            if span.start <= merged[-1].end and not any(joined.start < cut < joined.end for cut in cuts):
                merged[-1] = joined
                continue
        merged.append(span)
    return merged


def assemble(
    *,
    query: BucketedQuery,
    grid: BucketGrid,
    date_from: datetime,
    date_to: datetime,
    now: datetime,
    store: BucketStore,
    fetch: Callable[[datetime, datetime], SpanRows],
    limit: int,
    row_cap: Optional[int],
) -> BucketedAnswer:
    """The answer for [date_from, date_to): stored buckets, plus runs for what the store lacks and for the buckets
    that are not finished. Finished buckets fetched here join the store. `limit` caps the answer's rows, and
    `row_cap` is the most rows one run returns when the query has its own LIMIT."""
    if date_to <= date_from:
        raise NotBucketable("the range is empty")
    cutoff = min(date_to, now - query.settle)
    first = grid.ceil(date_from)
    finished_to = grid.floor(cutoff)
    storable = finished_to > first
    if storable and (finished_to - first) / grid.step > MAX_BUCKETS_PER_RANGE:
        raise NotBucketable(f"the range has more than {MAX_BUCKETS_PER_RANGE} buckets: use a larger bucket")

    expected, meta = store.read_meta() if storable else (b"", None)
    reset = False
    far = False
    if storable and meta is not None:
        gap = max(first - meta.end, meta.start - finished_to, timedelta(0))
        if gap > max(finished_to - first, grid.step):
            # Far from what is stored: a panel and its previous period share a store, a distant range does not.
            far = True
            storable = False
            meta = None
    if (
        storable
        and expected
        and (
            meta is None
            or now - meta.born > MAX_STORE_AGE
            or meta.size > MAX_STORE_BYTES
            or store.size() > MAX_STORED_BUCKETS
        )
    ):
        # Unreadable, too old, or grown past its cap: start over rather than trust what it claims.
        reset, meta = True, None

    served: Optional[Span] = None
    fills: list[Span] = []
    cover: Optional[Span] = None
    if storable:
        if meta is None:
            cover = Span(start=first, end=finished_to)
            fills = [cover]
        else:
            cover = Span(start=min(first, meta.start), end=max(finished_to, meta.end))
            fills = [Span(start=cover.start, end=meta.start), Span(start=meta.end, end=cover.end)]
            if max(first, meta.start) < min(finished_to, meta.end):
                served = Span(start=max(first, meta.start), end=min(finished_to, meta.end))
    answer_spans = (
        [Span(start=date_from, end=date_to)]
        if served is None
        else [Span(start=date_from, end=served.start), Span(start=served.end, end=date_to)]
    )
    cuts = {point for point in (date_from, date_to) if not grid.is_start(point)}
    spans = _merge_spans([*answer_spans, *fills], cuts)

    columns: list[Any] | None = meta.columns if meta is not None else None
    types: list[Any] | None = meta.types if meta is not None else None
    by_bucket: dict[datetime, list[list[Any]]] = {}
    to_store: dict[datetime, list[list[Any]]] = {}
    parts: list[Part] = []
    runs = _Runs(fetch, row_cap)
    claimed: set[Span] = set()
    for run in spans:
        start, end = run.start, run.end
        got = _fetch_split(runs, grid, start, end, now)
        columns, types = got.columns, got.types
        floor_start = grid.floor(start)
        rows_by_bucket: dict[datetime, list[list[Any]]] = {}
        for row in got.rows:
            if not row:
                raise BucketContractError("a row has no columns")
            bucket = _bucket_of(row[0], grid.tz)
            if not grid.is_start(bucket) or bucket < floor_start or bucket >= end:
                raise BucketContractError(
                    f"the first column must be the bucket start, {grid.unit} grid in the project timezone "
                    f"(got {row[0]!r} for {start.isoformat()} to {end.isoformat()})"
                )
            rows_by_bucket.setdefault(bucket, []).append(row)
        # The answer spans this run covers whole and no other run has claimed. A run that only fills the store may
        # overlap an answer span another run covers, and must not add its rows twice. A run with a cut inside it
        # holds rows of the cut bucket from outside the range, so it owns no answer span.
        cut_inside = any(start < cut < end for cut in cuts)
        owned = [
            span
            for span in answer_spans
            if not span.empty and span not in claimed and run.contains(span) and not cut_inside
        ]
        claimed.update(owned)
        for bucket, rows in rows_by_bucket.items():
            portion = max(bucket, start)
            in_answer = any(span.start <= portion < span.end for span in owned)
            if in_answer:
                by_bucket.setdefault(bucket, []).extend(rows)
            if (
                cover is not None
                and start <= bucket
                and cover.start <= bucket
                and grid.next(bucket) <= min(end, cover.end)
            ):
                to_store[bucket] = rows
        parts.append(Part(start=start, end=end, source="clickhouse"))

    stored: dict[datetime, list[list[Any]]] = {}
    if served is not None:
        held, stored = store.read(grid.starts(served.start, served.end))
        if held is None or not Span(start=held.start, end=held.end).contains(served):
            raise BucketStoreError("the store lost buckets while this range ran")
        parts.append(Part(start=served.start, end=served.end, source="store"))

    if columns is None or types is None:
        # Nothing ran and nothing was stored with its columns: a store from before columns were kept.
        raise BucketContractError("the store has no columns")

    try:
        if cover is not None and any(not fill.empty for fill in fills):
            packed = {bucket: pack(rows) for bucket, rows in to_store.items()}
            size = sum(len(value) for value in packed.values())
            if size > MAX_STORE_BYTES:
                BUCKETED_RUNS.labels(outcome="too_large").inc()
            else:
                new_meta = StoreMeta(
                    start=cover.start,
                    end=cover.end,
                    columns=columns,
                    types=types,
                    born=now if meta is None else meta.born,
                    size=size if meta is None else meta.size + size,
                )
                if not store.write(expected=expected, meta=new_meta, buckets=packed, reset=reset):
                    BUCKETED_RUNS.labels(outcome="write_conflict").inc()
        elif served is not None:
            store.touch()
    except BucketStoreError:
        # The answer is already computed: serve it and keep the store as it was.
        BUCKETED_RUNS.labels(outcome="write_failed").inc()
        logger.warning("dashboard_v2_bucket_store_write_failed", store_key=store.key, exc_info=True)

    fetched = {bucket: _json_rows(rows) for bucket, rows in by_bucket.items()}
    combined = {**stored, **fetched}
    ordered = sorted(combined, reverse=query.order == "DESC")
    rows = [row for bucket in ordered for row in combined[bucket]]
    has_more = len(rows) > limit
    return BucketedAnswer(
        columns=columns,
        types=types,
        rows=rows[:limit],
        has_more=has_more,
        parts=sorted(parts, key=lambda part: part.start),
        stored_buckets=len(stored),
        far=far,
    )


def finished_rows(rows: list[list[Any]], *, grid: BucketGrid, finished_before: datetime) -> list[str]:
    """Rows of buckets that ended before `finished_before`, as sortable JSON, for comparing two answers."""
    out = []
    for row in rows:
        bucket = _bucket_of(row[0], grid.tz)
        if grid.next(bucket) <= finished_before:
            out.append(json.dumps(row, sort_keys=True, default=str))
    return sorted(out)


_shadow_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dashboard-v2-bucket-shadow")
_shadow_slots = BoundedSemaphore(4)


def maybe_shadow_check(
    *,
    answer: BucketedAnswer,
    grid: BucketGrid,
    query: BucketedQuery,
    date_from: datetime,
    date_to: datetime,
    now: datetime,
    fetch: Callable[[datetime, datetime], SpanRows],
    store_key: str,
    on_done: Callable[[], None] = lambda: None,
) -> bool:
    """Sometimes runs the whole range in the background and compares its finished buckets with the assembled ones.
    Off unless DASHBOARD_V2_BUCKET_SHADOW_RATE is set."""
    rate = float(getattr(settings, "DASHBOARD_V2_BUCKET_SHADOW_RATE", 0.0))
    if rate <= 0 or random.random() >= rate or answer.has_more:
        return False
    if not _shadow_slots.acquire(blocking=False):
        SHADOW_CHECKS.labels(outcome="skipped").inc()
        return False

    def check() -> None:
        try:
            whole = fetch(date_from, date_to)
            if whole.has_more:
                SHADOW_CHECKS.labels(outcome="skipped").inc()
                return
            finished_before = grid.floor(min(date_to, now - query.settle))
            expected = finished_rows(_json_rows(whole.rows), grid=grid, finished_before=finished_before)
            actual = finished_rows(answer.rows, grid=grid, finished_before=finished_before)
            if expected == actual:
                SHADOW_CHECKS.labels(outcome="match").inc()
            else:
                SHADOW_CHECKS.labels(outcome="mismatch").inc()
                logger.warning(
                    "dashboard_v2_bucketed_shadow_mismatch",
                    store_key=store_key,
                    expected_rows=len(expected),
                    actual_rows=len(actual),
                )
        except Exception:
            SHADOW_CHECKS.labels(outcome="error").inc()
            logger.warning("dashboard_v2_bucketed_shadow_failed", store_key=store_key, exc_info=True)
        finally:
            _shadow_slots.release()
            on_done()

    try:
        _shadow_pool.submit(copy_context().run, check)
    except RuntimeError:
        _shadow_slots.release()
        return False
    return True


def provenance(answer: BucketedAnswer, grid: BucketGrid) -> dict[str, Any]:
    return {
        "mode": "derived",
        "bucketed": {"interval": f"{grid.size} {grid.unit}", "stored": answer.stored_buckets},
        "parts": [
            {"from": part.start.isoformat(), "to": part.end.isoformat(), "source": part.source} for part in answer.parts
        ],
    }


def raw_provenance(reason: str) -> dict[str, Any]:
    return {"mode": "raw", "reason": reason, "parts": []}
