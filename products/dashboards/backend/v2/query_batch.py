"""The `dashboard-v2` query batch: many panels' queries in one request, each result streamed back as an NDJSON line.

A panel holds its query inline, as a Dash target does, instead of pointing at an insight, so no Insight or
DashboardTile row is read. Every query is planned for the requesting user, so its cache key carries their access
restrictions, and every planned entry is read in one round trip. Hits are written first. Misses then run as `/query`
runs them, a few at a time, and each line is written the moment its query finishes.
"""

import json
import math
import asyncio
import weakref
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime
from functools import partial
from queue import Empty, Queue
from threading import BoundedSemaphore, Event, Lock, Semaphore, Thread, Timer
from time import monotonic
from typing import Any, Optional
from uuid import UUID

from django.db import connections
from django.utils.timezone import now

import structlog
from pydantic import BaseModel

from posthog.schema import CacheMissResponse, IntervalType

from posthog.hogql.constants import LimitContext
from posthog.hogql.errors import ExposedHogQLError, ResolutionError

from posthog.api.services.query import (
    ExecutionMode,
    PlannedQuery,
    plan_query_dict,
    process_query_dict,
    run_planned_query,
)
from posthog.api.utils import is_async_query, is_insight_actors_options_query, is_insight_actors_query
from posthog.clickhouse.cancel import cancel_query_on_cluster
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import tags_context
from posthog.dataclasses import frozen
from posthog.errors import ExposedCHQueryError
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.user import User
from posthog.renderers import SafeJSONRenderer

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.dashboards.backend.facade.contracts import QueryBatchBusy, QueryBatchInput
from products.dashboards.backend.facade.enums import QueryBatchLanguage
from products.dashboards.backend.v2.cached_tiles import planned_cache_reads

logger = structlog.get_logger(__name__)

MAX_QUERIES_PER_BATCH = 500
WORKERS_PER_BATCH = 4
MAX_CONCURRENT_BATCHES = 8
HEARTBEAT_SECONDS = 10.0
MAX_READY_BYTES = 128 * 1024 * 1024
# Every cache hit rendered, kept or not, so oversized entries cannot be read and dropped without end.
MAX_READ_BYTES = 4 * MAX_READY_BYTES
CACHE_READ_CHUNK = 5
MAX_UNREAD_LINES = WORKERS_PER_BATCH
CANCEL_RETRY_SECONDS = 2.0
CANCEL_WINDOW_SECONDS = 120.0
_batch_slots = BoundedSemaphore(MAX_CONCURRENT_BATCHES)
MAX_BATCHES_PER_ORG = 3
MAX_OPEN_BATCHES = 16
MAX_OPEN_BATCHES_PER_ORG = 4
OPEN_WAIT_SECONDS = 10.0
MAX_STREAM_SECONDS = 600.0
_open_slots = BoundedSemaphore(MAX_OPEN_BATCHES)
_org_open: dict[UUID, int] = {}
_org_batches: dict[UUID, int] = {}
_org_lock = Lock()
# Finalizers only queue a release: one can run during garbage collection while this thread holds `_org_lock`.
_deferred_releases: deque["_OpenSlot"] = deque()


def _admit_batch(org_id: UUID) -> bool:
    # A per-organization share below the process cap, so one organization's slow readers cannot hold every slot.
    with _org_lock:
        if _org_batches.get(org_id, 0) >= MAX_BATCHES_PER_ORG:
            return False
        if not _batch_slots.acquire(blocking=False):
            return False
        _org_batches[org_id] = _org_batches.get(org_id, 0) + 1
        return True


class _OpenSlot:
    """A batch's place among the open batches, from its cache read until its stream closes, because it holds its
    cached results all that time. Released once, by the stream or, if the stream never runs, when the batch is
    collected."""

    def __init__(self, org_id: UUID) -> None:
        self._org_id = org_id
        self._held = False

    def acquire(self) -> bool:
        _drain_deferred_releases()
        deadline = monotonic() + OPEN_WAIT_SECONDS
        with _org_lock:
            if _org_open.get(self._org_id, 0) >= MAX_OPEN_BATCHES_PER_ORG:
                return False
            _org_open[self._org_id] = _org_open.get(self._org_id, 0) + 1
        if not _open_slots.acquire(timeout=max(0.0, deadline - monotonic())):
            self._release_org()
            return False
        self._held = True
        return True

    def release(self) -> None:
        with _org_lock:
            if not self._held:
                return
            self._held = False
        _open_slots.release()
        self._release_org()

    def _release_org(self) -> None:
        with _org_lock:
            count = _org_open.get(self._org_id, 0) - 1
            if count > 0:
                _org_open[self._org_id] = count
            else:
                _org_open.pop(self._org_id, None)


def _drain_deferred_releases() -> None:
    while True:
        try:
            slot = _deferred_releases.popleft()
        except IndexError:
            return
        slot.release()


def _release_batch(org_id: UUID) -> None:
    with _org_lock:
        count = _org_batches.get(org_id, 0) - 1
        if count > 0:
            _org_batches[org_id] = count
        else:
            _org_batches.pop(org_id, None)
        _batch_slots.release()


REFRESH_WORKERS = 2
MAX_QUEUED_REFRESHES = 64
MAX_REFRESHES_PER_BATCH = 20
_refresh_pool = ThreadPoolExecutor(max_workers=REFRESH_WORKERS, thread_name_prefix="dashboard-query-batch-refresh")
_refresh_slots = BoundedSemaphore(MAX_QUEUED_REFRESHES)

_FAILED = "The query failed."
_THROTTLED = "Too many queries are running for this organization. Try again shortly."
_BUSY = "Too many dashboards are loading at once. Try again shortly."
_TIMED_OUT = "The dashboard took too long to load. Try again."
_TIMED_OUT_BODY = json.dumps({"error": _TIMED_OUT}).encode()
_TOO_LARGE = "The cached results in this request are too large to send together. Request fewer panels at once."
_INTERVAL_KINDS = frozenset({"TrendsQuery", "StickinessQuery", "LifecycleQuery", "FunnelsQuery"})
# Rate-limited per team on `/query` for its CPU cost, which a batch's per-request admission cannot account for.
_UNBATCHABLE_KINDS = frozenset({"ErrorTrackingFingerprintProjectionQuery"})
_WRAPPER_KINDS = frozenset({"InsightVizNode", "DataVisualizationNode", "DataTableNode"})
_EXPOSED_ERRORS = (ExposedHogQLError, ExposedCHQueryError, ResolutionError, UserAccessControlError)


class InvalidTarget(ValueError):
    pass


@frozen
class ResolvedQuery:
    """A batch input as the arguments `/query` takes."""

    query: dict[str, Any]
    filters: Optional[dict[str, Any]]
    variables: Optional[dict[str, Any]]


def to_posthog_date(expression: str) -> Optional[str]:
    """A time expression as a PostHog date, kept relative so the cache key stays the same across reloads:
    `now-14d` is `-14d`, `now-30m` is `-30M` and `now-3M` is `-3m` (PostHog's `m` is months), `now` is None."""
    if expression == "now":
        return None
    if expression.startswith("now-") and len(expression) > 5 and expression[4:-1].isdigit():
        amount, unit = int(expression[4:-1]), expression[-1]
        if unit == "s":
            return f"-{max(1, math.ceil(amount / 60))}M"
        if unit in "mMhdwy":
            posthog_unit = {"m": "M", "M": "m"}.get(unit, unit)
            return f"-{amount}{posthog_unit}"
    try:
        datetime.fromisoformat(expression)
    except ValueError:
        raise InvalidTarget(f"Unsupported time expression: {expression!r}. Use now, now-<n><s|m|h|d|w|M|y>, or ISO.")
    return expression


def resolve_query(item: QueryBatchInput) -> ResolvedQuery:
    date_from, date_to = to_posthog_date(item.date_from), to_posthog_date(item.date_to)
    target = item.target
    if target.language == QueryBatchLanguage.HOGQL:
        return ResolvedQuery(
            query={
                "kind": "HogQLQuery",
                "query": target.query,
                "filters": {"dateRange": {"date_from": date_from, "date_to": date_to}},
            },
            filters=None,
            variables=item.variables,
        )
    try:
        parsed = json.loads(target.query)
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("query"), dict) or "kind" not in parsed["query"]:
        raise InvalidTarget('An insight target is JSON: {"query": {"kind": ...}, "filters"?, "variables"?}.')
    query: dict[str, Any] = parsed["query"]
    source = query.get("source")
    kinds = {query["kind"], source.get("kind") if isinstance(source, dict) else None}
    if blocked := kinds & _UNBATCHABLE_KINDS:
        raise InvalidTarget(f"{blocked.pop()} can't be batched. Use /query.")
    raw_filters = parsed.get("filters")
    filters: dict[str, Any] = raw_filters if isinstance(raw_filters, dict) else {}
    # A target that sets its own date_from pins its range, as a tile's date override does.
    if "date_from" not in filters:
        filters = {**filters, "date_from": date_from, "date_to": date_to}
    if item.interval:
        query = _with_interval(query, item.interval)
    variables = item.variables if item.variables is not None else parsed.get("variables")
    return ResolvedQuery(query=query, filters=filters, variables=variables if isinstance(variables, dict) else None)


def _with_interval(query: dict[str, Any], interval: str) -> dict[str, Any]:
    if interval not in {member.value for member in IntervalType}:
        raise InvalidTarget(f"Unsupported interval: {interval!r}.")
    if query.get("kind") in _WRAPPER_KINDS and isinstance(query.get("source"), dict):
        return {**query, "source": _with_interval(query["source"], interval)}
    return {**query, "interval": interval} if query.get("kind") in _INTERVAL_KINDS else query


def _limit_context(query: dict[str, Any]) -> Optional[LimitContext]:
    # The limit `/query` gives the same query, so a computed miss gets the same timeout there and here.
    if is_async_query(query) or is_insight_actors_query(query) or is_insight_actors_options_query(query):
        return LimitContext.QUERY_ASYNC
    return None


def _is_stale(response: object) -> bool:
    # The rule the dashboard client applies to decide which tiles to refresh.
    target_age = getattr(response, "cache_target_age", None)
    return not isinstance(target_age, datetime) or target_age <= now()


def _result_line(index: int, response: Any, *, hit: bool, stale: bool) -> dict[str, Any]:
    result = response.model_dump(by_alias=True) if isinstance(response, BaseModel) else response
    if result.get("error"):
        return {"i": index, "error": str(result["error"])}
    line: dict[str, Any] = {
        "i": index,
        "result": {
            "result": result,
            "cache": {
                "key": result.get("cache_key"),
                "fetchedAt": result.get("last_refresh"),
                "stale": stale,
                "hit": hit,
            },
        },
    }
    if result.get("provenance") is not None:
        line["result"]["provenance"] = result["provenance"]
    return line


def _miss_line(index: int, cache_key: Optional[str]) -> dict[str, Any]:
    return {
        "i": index,
        "result": {"result": None, "cache": {"key": cache_key, "fetchedAt": None, "stale": False, "hit": False}},
    }


@frozen
class _ServedKey:
    """Panels with equal keys can share one rendered hit. The cache key leaves out series names, which a hit patches
    per query, so the query is part of the key."""

    cache_key: str
    swr: bool
    cache_only: bool
    query: str


def _served_key(planned: PlannedQuery, item: QueryBatchInput) -> _ServedKey:
    return _ServedKey(
        cache_key=planned.cache_key,
        swr=item.swr,
        cache_only=item.cache_only,
        query=json.dumps(planned.upgraded_query, sort_keys=True, default=str),
    )


def _error_line(index: int, error: Exception, *, team: Team) -> dict[str, Any]:
    if isinstance(error, (*_EXPOSED_ERRORS, InvalidTarget)):
        message = str(error)
    elif isinstance(error, ConcurrencyLimitExceeded):
        message = _THROTTLED
    else:
        logger.warning("dashboard_v2_query_batch_item_failed", team_id=team.pk, exc_info=True)
        capture_exception(error)
        message = _FAILED
    return {"i": index, "error": message}


def _refresh_all(*, team: Team, user: User, dashboard_id: Optional[int], queries: list[ResolvedQuery]) -> None:
    # The stale results are already in the response. The async path recomputes them for the next read.
    try:
        for query in queries:
            try:
                process_query_dict(
                    team,
                    query.query,
                    dashboard_filters_json=query.filters,
                    variables_override_json=query.variables,
                    limit_context=_limit_context(query.query),
                    execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
                    user=user,
                    dashboard_id=dashboard_id,
                )
            except Exception:
                logger.warning("dashboard_v2_query_batch_refresh_failed", team_id=team.pk, exc_info=True)
    finally:
        connections.close_all()
        for _query in queries:
            _refresh_slots.release()


def _expire_if_alive(batch_ref: "weakref.ReferenceType[QueryBatch]") -> None:
    batch = batch_ref()
    if batch is not None:
        batch._expire()


def _render_body(line: dict[str, Any]) -> bytes:
    return SafeJSONRenderer().render({key: value for key, value in line.items() if key != "i"})


type _Job = Callable[[], dict[str, Any]]


class QueryBatch:
    """Plans and reads the cache for every input when built, in the request thread. `stream` and `astream` then write
    those lines, run the queries that still need it, and write each of their lines as it finishes."""

    def __init__(
        self,
        *,
        team: Team,
        user: User,
        inputs: Sequence[QueryBatchInput],
        dashboard_id: Optional[int],
        client_query_id: str,
    ) -> None:
        self._team = team
        self._user = user
        self._dashboard_id = dashboard_id
        self._client_query_id = client_query_id
        # Each line's JSON without its `i`, so panels that share a cache entry share one copy of its result.
        self.ready: list[tuple[int, bytes]] = []
        self._ready_bytes = 0
        self._read_bytes = 0
        # Taken while the request is live: the middleware resets the query tags and team scope before streaming.
        self._context = copy_context()
        self._jobs: list[tuple[int, str, _Job]] = []
        self._queue: Queue[dict[str, Any]] = Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_queue: asyncio.Queue[dict[str, Any]] | None = None
        self._pool: ThreadPoolExecutor | None = None
        self._futures: list[Future[None]] = []
        self._active: set[str] = set()
        self._cancelled = False
        self._admitted = False
        self._to_refresh: list[ResolvedQuery] = []
        self._lock = Lock()
        self._idle = Event()
        self._unread = Semaphore(MAX_UNREAD_LINES)
        self._closed = False
        self._deadline = monotonic() + MAX_STREAM_SECONDS
        self._open = _OpenSlot(team.organization_id)
        if not self._open.acquire():
            raise QueryBatchBusy()
        weakref.finalize(self, _deferred_releases.append, self._open)
        try:
            self._read_cache(inputs)
        except BaseException:
            self._open.release()
            raise
        # A client that stops reading parks the stream inside a send, where no deadline check runs, so a timer
        # enforces it: it drops the held results, frees the run slot and cancels running queries.
        # A weak target, so a response dropped before it is iterated is still collected and its slot released.
        self._watchdog = Timer(max(0.0, self._deadline - monotonic()), _expire_if_alive, args=(weakref.ref(self),))
        self._watchdog.daemon = True
        self._watchdog.start()

    def _read_cache(self, inputs: Sequence[QueryBatchInput]) -> None:
        resolved: dict[int, ResolvedQuery] = {}
        for index, item in enumerate(inputs):
            try:
                resolved[index] = resolve_query(item)
            except InvalidTarget as e:
                self._add_ready({"i": index, "error": str(e)})
        user_access_control = UserAccessControl(user=self._user, team=self._team)

        def plan(index: int) -> PlannedQuery | None:
            query = resolved[index]
            return plan_query_dict(
                self._team,
                query.query,
                dashboard_filters_json=query.filters,
                variables_override_json=query.variables,
                limit_context=_limit_context(query.query),
                user=self._user,
                user_access_control=user_access_control,
                allow_raw_results=False,
            )

        to_run: list[int] = []
        to_refresh: list[int] = []
        served: dict[_ServedKey, bytes] = {}
        indices = list(resolved)
        for chunk_start in range(0, len(indices), CACHE_READ_CHUNK):
            chunk = indices[chunk_start : chunk_start + CACHE_READ_CHUNK]
            if monotonic() >= self._deadline:
                for index in chunk:
                    self._add_ready({"i": index, "error": _TIMED_OUT})
                continue
            if self._ready_bytes >= MAX_READY_BYTES or self._read_bytes >= MAX_READ_BYTES:
                # Past the budget, later entries are never fetched, so their blobs are not downloaded either.
                for index in chunk:
                    self._add_ready({"i": index, "error": _TOO_LARGE})
                continue
            self._read_chunk(inputs, resolved, chunk, plan, to_run, to_refresh, served)

        self._to_refresh = [resolved[index] for index in to_refresh]
        for index in to_run:
            query_id = f"{self._client_query_id}-{index}"
            self._jobs.append((index, query_id, partial(self._run, index, resolved[index], query_id)))

    def _read_chunk(
        self,
        inputs: Sequence[QueryBatchInput],
        resolved: dict[int, ResolvedQuery],
        chunk: list[int],
        plan: Callable[[int], PlannedQuery | None],
        to_run: list[int],
        to_refresh: list[int],
        served: dict[_ServedKey, bytes],
    ) -> None:
        duplicates: dict[int, bytes] = {}

        def plan_unserved(index: int) -> PlannedQuery | None:
            # A panel repeating an entry an earlier chunk served is left unplanned, so its blob is not fetched again.
            planned = plan(index)
            if planned is not None:
                body = served.get(_served_key(planned, inputs[index]))
                if body is not None:
                    duplicates[index] = body
                    return None
            return planned

        with planned_cache_reads(
            team=self._team, distinct_id=str(self._user.distinct_id), keys=chunk, plan=plan_unserved
        ) as planned_queries:
            for index in chunk:
                item = inputs[index]
                if index in duplicates:
                    self._add_shared(index, duplicates[index])
                    continue
                planned = planned_queries.get(index)
                if planned is None:
                    if item.cache_only:
                        self._add_ready(_miss_line(index, None))
                    else:
                        # Unplannable queries run unplanned below, so `/query`'s own validation reports why.
                        to_run.append(index)
                    continue
                if planned.query_runner.requires_fresh_calculation():
                    # Never served from the cache, cache-only or not, as `/query` never serves it.
                    if item.cache_only:
                        self._add_ready(_miss_line(index, planned.cache_key))
                    else:
                        to_run.append(index)
                    continue
                same_entry = _served_key(planned, item)
                if same_entry in served:
                    self._add_shared(index, served[same_entry])
                    continue
                try:
                    response = run_planned_query(
                        planned,
                        execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
                        user=self._user,
                        insight_id=None,
                        dashboard_id=self._dashboard_id,
                        cache_age_seconds=None,
                        analytics_props=None,
                    )
                except Exception as e:
                    self._add_ready(_error_line(index, e, team=self._team))
                    continue
                if isinstance(response, CacheMissResponse):
                    if item.cache_only:
                        self._add_ready(_miss_line(index, planned.cache_key))
                    else:
                        to_run.append(index)
                    continue
                stale = _is_stale(response)
                if stale and not (item.swr or item.cache_only):
                    to_run.append(index)
                    continue
                body = _render_body(_result_line(index, response, hit=True, stale=stale))
                del response
                self._read_bytes += len(body)
                if self._ready_bytes + len(body) > MAX_READY_BYTES:
                    # Shared like a served body, so panels repeating this entry are not fetched and rendered again.
                    served[same_entry] = self._add_ready({"i": index, "error": _TOO_LARGE})
                    continue
                self.ready.append((index, body))
                self._ready_bytes += len(body)
                served[same_entry] = body
                if stale and item.swr and not item.cache_only:
                    to_refresh.append(index)

    def _add_ready(self, line: dict[str, Any]) -> bytes:
        body = _render_body(line)
        self.ready.append((line["i"], body))
        self._ready_bytes += len(body)
        return body

    def _add_shared(self, index: int, body: bytes) -> None:
        # Shared in memory but written once per panel, so it counts against the budget each time.
        if self._ready_bytes + len(body) > MAX_READY_BYTES:
            self._add_ready({"i": index, "error": _TOO_LARGE})
            return
        self.ready.append((index, body))
        self._ready_bytes += len(body)

    def _ready_lines(self) -> Iterator[bytes]:
        # By position, not a list iterator, so `_drop_ready` can swap the list and free the bodies not yet sent.
        position = 0
        while position < len(self.ready):
            if monotonic() >= self._deadline:
                self._drop_ready()
            index, body = self.ready[position]
            position += 1
            yield b'{"i":%d,' % index + body[1:] + b"\n"

    def _drop_ready(self) -> None:
        self.ready = [(index, _TIMED_OUT_BODY) for index, _body in self.ready]

    def _expire(self) -> None:
        # The open slot stays held until the response closes. Dropping every buffered result is what keeps a stalled
        # stream cheap, so a fresh batch admitted later is never added on top of results nobody will read.
        self._drop_ready()
        self._close(False)
        self._drain_queues()

    def _drain_queues(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                break
        if self._loop is not None and self._async_queue is not None:
            queue = self._async_queue

            def clear() -> None:
                while not queue.empty():
                    queue.get_nowait()

            try:
                self._loop.call_soon_threadsafe(clear)
            except RuntimeError:
                pass

    def _dispatch_refreshes(self) -> None:
        # After the cached lines are written, so a stale board is not held back by its own refreshes.
        if not self._to_refresh:
            return
        candidates, self._to_refresh = self._to_refresh[:MAX_REFRESHES_PER_BATCH], []
        # One slot per query, since each enqueues its own calculation. A refresh that finds the queue full is dropped:
        # the stale result is already served and the next read retries.
        queries: list[ResolvedQuery] = []
        for query in candidates:
            if not _refresh_slots.acquire(blocking=False):
                break
            queries.append(query)
        if not queries:
            return

        # Only what a refresh needs, so a queued refresh does not keep this batch's buffered results alive.
        refresh_all = partial(
            _refresh_all,
            team=self._team,
            user=self._user,
            dashboard_id=self._dashboard_id,
            queries=queries,
        )
        try:
            _refresh_pool.submit(self._context.copy().run, refresh_all)
        except RuntimeError:
            for _query in queries:
                _refresh_slots.release()

    def _run(self, index: int, query: ResolvedQuery, query_id: str) -> dict[str, Any]:
        if self._cancelled:
            return {"i": index, "error": _FAILED}
        try:
            response = process_query_dict(
                self._team,
                query.query,
                dashboard_filters_json=query.filters,
                variables_override_json=query.variables,
                limit_context=_limit_context(query.query),
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                user=self._user,
                query_id=query_id,
                dashboard_id=self._dashboard_id,
            )
        except Exception as e:
            return _error_line(index, e, team=self._team)
        return _result_line(index, response, hit=False, stale=False)

    def _emit(self, line: dict[str, Any]) -> None:
        if self._is_cancelled():
            return
        if self._loop is None or self._async_queue is None:
            self._queue.put(line)
            return
        try:
            self._loop.call_soon_threadsafe(self._async_queue.put_nowait, line)
        except RuntimeError:
            pass

    def _is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def _work(self, job: _Job, query_id: str) -> None:
        try:
            with self._lock:
                if self._cancelled:
                    return
                self._active.add(query_id)
            with tags_context(team_id=self._team.pk, client_query_id=query_id):
                line = job()
            # Waits while the client is behind, so a slow reader holds a few results, not every finished one.
            while not self._unread.acquire(timeout=1.0):
                if self._is_cancelled():
                    return
            self._emit(line)
        finally:
            with self._lock:
                self._active.discard(query_id)
                if self._cancelled and not self._active:
                    self._idle.set()
            connections.close_all()

    def _start(self) -> bool:
        if not self._jobs:
            return True
        # Under the lock, so the watchdog's `_close` sees either no admission or one with all of its futures.
        with self._lock:
            if self._closed:
                return False
            self._admitted = _admit_batch(self._team.organization_id)
            if not self._admitted:
                return False
            self._pool = ThreadPoolExecutor(max_workers=WORKERS_PER_BATCH, thread_name_prefix="dashboard-query-batch")
            for _index, query_id, job in self._jobs:
                self._futures.append(self._pool.submit(self._context.copy().run, self._work, job, query_id))
        return True

    def _close(self, complete: bool) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cancelled = True
            active = tuple(self._active)
            admitted, self._admitted = self._admitted, False
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
        if not complete and active:
            # The client went away: stop what is still running in ClickHouse. A worker that was still planning
            # or waiting for a limiter slot sends its SQL after the first kill, so keep killing until it ends.
            Thread(
                target=self._cancel_until_idle, args=(active,), daemon=True, name="dashboard-query-batch-cancel"
            ).start()
        if admitted:
            for future in self._futures:
                future.cancel()
            # A running query keeps its thread after a disconnect, so the slot is freed when the last one ends.
            remaining = [future for future in self._futures if not future.done()]
            if not remaining:
                _release_batch(self._team.organization_id)
            else:
                pending = [len(remaining)]
                counter_lock = Lock()

                def done(_future: Future[None]) -> None:
                    with counter_lock:
                        pending[0] -= 1
                        last = pending[0] == 0
                    if last:
                        _release_batch(self._team.organization_id)

                for future in remaining:
                    future.add_done_callback(done)

    def _cancel_until_idle(self, active: tuple[str, ...]) -> None:
        deadline = monotonic() + CANCEL_WINDOW_SECONDS
        while active:
            for query_id in active:
                try:
                    cancel_query_on_cluster(team_id=self._team.pk, client_query_id=query_id)
                except Exception:
                    logger.exception("dashboard_v2_query_batch_cancel_failed", team_id=self._team.pk)
            if monotonic() >= deadline or self._idle.wait(CANCEL_RETRY_SECONDS):
                return
            with self._lock:
                active = tuple(self._active)

    @staticmethod
    def _encode(line: dict[str, Any]) -> bytes:
        return SafeJSONRenderer().render(line) + b"\n"

    def _timed_out_lines(self, pending: set[int]) -> Iterator[bytes]:
        for index in sorted(pending):
            yield self._encode({"i": index, "error": _TIMED_OUT})

    def _busy_lines(self) -> Iterator[bytes]:
        message = _TIMED_OUT if self._closed else _BUSY
        for index, _query_id, _job in self._jobs:
            yield self._encode({"i": index, "error": message})

    def stream(self) -> Iterator[bytes]:
        try:
            yield from self._stream()
        finally:
            self._watchdog.cancel()
            self._open.release()

    async def astream(self) -> AsyncIterator[bytes]:
        body = self._astream()
        try:
            async for chunk in body:
                yield chunk
        finally:
            self._watchdog.cancel()
            await body.aclose()
            self._open.release()

    def _stream(self) -> Iterator[bytes]:
        yield from self._ready_lines()
        self._dispatch_refreshes()
        if not self._start():
            yield from self._busy_lines()
            return
        complete = False
        deadline = self._deadline
        pending = {index for index, _query_id, _job in self._jobs}
        try:
            while pending:
                if monotonic() >= deadline:
                    yield from self._timed_out_lines(pending)
                    return
                try:
                    line = self._queue.get(timeout=HEARTBEAT_SECONDS)
                except Empty:
                    # Proxies close a response that sends nothing for a while, which would end the batch early.
                    yield b"\n"
                    continue
                pending.discard(line["i"])
                yield self._encode(line)
                self._unread.release()
            complete = True
        finally:
            self._close(complete)

    async def _astream(self) -> AsyncGenerator[bytes]:
        for chunk in self._ready_lines():
            yield chunk
        self._dispatch_refreshes()
        self._loop = asyncio.get_running_loop()
        self._async_queue = asyncio.Queue()
        if not self._start():
            for chunk in self._busy_lines():
                yield chunk
            return
        complete = False
        deadline = self._deadline
        pending = {index for index, _query_id, _job in self._jobs}
        try:
            while pending:
                if monotonic() >= deadline:
                    for chunk in self._timed_out_lines(pending):
                        yield chunk
                    return
                try:
                    line = await asyncio.wait_for(self._async_queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield b"\n"
                    continue
                pending.discard(line["i"])
                yield self._encode(line)
                self._unread.release()
            complete = True
        finally:
            # A thread of its own: cancelling on the cluster blocks, and slow queries can fill the loop's executor.
            Thread(target=self._close, args=(complete,), daemon=True, name="dashboard-query-batch-close").start()
