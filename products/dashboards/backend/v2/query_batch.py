"""The `dashboard-v2` query batch: many panels' queries in one request, each result streamed back as an NDJSON line.

A panel holds its query inline, as a Dash target does, instead of pointing at an insight, so no Insight or
DashboardTile row is read. Every query is planned for the requesting user, so its cache key carries their access
restrictions, and every planned entry is read in one round trip. Hits are written first. Misses then run as `/query`
runs them, a few at a time, and each line is written the moment its query finishes.
"""

import json
import math
import asyncio
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from datetime import datetime
from functools import partial
from queue import Empty, Queue
from threading import BoundedSemaphore, Lock, Thread
from typing import Any, Optional

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
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner, range_based_freshness
from posthog.models.team import Team
from posthog.models.user import User
from posthog.renderers import SafeJSONRenderer

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.dashboards.backend.facade.contracts import QueryBatchInput
from products.dashboards.backend.facade.enums import QueryBatchLanguage
from products.dashboards.backend.v2.cached_tiles import planned_cache_reads

logger = structlog.get_logger(__name__)

MAX_QUERIES_PER_BATCH = 500
WORKERS_PER_BATCH = 4
MAX_CONCURRENT_BATCHES = 8
HEARTBEAT_SECONDS = 10.0
_batch_slots = BoundedSemaphore(MAX_CONCURRENT_BATCHES)

_FAILED = "The query failed."
_THROTTLED = "Too many queries are running for this organization. Try again shortly."
_BUSY = "Too many dashboards are loading at once. Try again shortly."
_INTERVAL_KINDS = frozenset({"TrendsQuery", "StickinessQuery", "LifecycleQuery", "FunnelsQuery"})
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


def _is_stale(response: object, planned: PlannedQuery) -> bool:
    # The rule the dashboard client applies to decide which tiles to refresh.
    target_age = getattr(response, "cache_target_age", None)
    runner = planned.query_runner
    last_refresh = getattr(response, "last_refresh", None)
    if (
        isinstance(runner, HogQLQueryRunner)
        and runner.range_freshness_interval is not None
        and isinstance(last_refresh, datetime)
    ):
        # The entry may have been stored by a run outside this batch, which uses the flat SQL rule.
        target_age = runner.cache_target_age(last_refresh)
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


def _miss_line(index: int, cache_key: str) -> dict[str, Any]:
    return {
        "i": index,
        "result": {"result": None, "cache": {"key": cache_key, "fetchedAt": None, "stale": False, "hit": False}},
    }


def _error_line(index: int, error: Exception, *, team: Team) -> dict[str, Any]:
    if isinstance(error, _EXPOSED_ERRORS | InvalidTarget):
        message = str(error)
    elif isinstance(error, ConcurrencyLimitExceeded):
        message = _THROTTLED
    else:
        logger.warning("dashboard_v2_query_batch_item_failed", team_id=team.pk, exc_info=True)
        capture_exception(error)
        message = _FAILED
    return {"i": index, "error": message}


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
        self.ready: list[dict[str, Any]] = []
        self._jobs: list[tuple[int, str, _Job]] = []
        self._queue: Queue[dict[str, Any]] = Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_queue: asyncio.Queue[dict[str, Any]] | None = None
        self._pool: ThreadPoolExecutor | None = None
        self._futures: list[Future[None]] = []
        self._active: set[str] = set()
        self._cancelled = False
        self._admitted = False
        self._lock = Lock()
        self._read_cache(inputs)

    def _read_cache(self, inputs: Sequence[QueryBatchInput]) -> None:
        resolved: dict[int, ResolvedQuery] = {}
        for index, item in enumerate(inputs):
            try:
                resolved[index] = resolve_query(item)
            except InvalidTarget as e:
                self.ready.append({"i": index, "error": str(e)})
        user_access_control = UserAccessControl(user=self._user, team=self._team)

        def plan(index: int) -> PlannedQuery | None:
            query = resolved[index]
            with range_based_freshness():
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
        with planned_cache_reads(
            team=self._team, distinct_id=str(self._user.distinct_id), keys=list(resolved), plan=plan
        ) as planned_queries:
            for index in resolved:
                item = inputs[index]
                planned = planned_queries.get(index)
                if planned is None:
                    # Unplannable queries run unplanned below, so `/query`'s own validation reports why.
                    to_run.append(index)
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
                    self.ready.append(_error_line(index, e, team=self._team))
                    continue
                if isinstance(response, CacheMissResponse):
                    if item.cache_only:
                        self.ready.append(_miss_line(index, planned.cache_key))
                    else:
                        to_run.append(index)
                    continue
                stale = _is_stale(response, planned)
                if stale and not (item.swr or item.cache_only):
                    to_run.append(index)
                    continue
                self.ready.append(_result_line(index, response, hit=True, stale=stale))
                if stale and item.swr and not item.cache_only:
                    to_refresh.append(index)

        for index in to_refresh:
            self._refresh_in_background(resolved[index])
        for index in to_run:
            query_id = f"{self._client_query_id}-{index}"
            self._jobs.append((index, query_id, partial(self._run, index, resolved[index], query_id)))

    def _refresh_in_background(self, query: ResolvedQuery) -> None:
        # The stale result is already in the response. The async path recomputes it for the next read.
        try:
            with range_based_freshness():
                process_query_dict(
                    self._team,
                    query.query,
                    dashboard_filters_json=query.filters,
                    variables_override_json=query.variables,
                    limit_context=_limit_context(query.query),
                    execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE,
                    user=self._user,
                    dashboard_id=self._dashboard_id,
                )
        except Exception:
            logger.warning("dashboard_v2_query_batch_refresh_failed", team_id=self._team.pk, exc_info=True)

    def _run(self, index: int, query: ResolvedQuery, query_id: str) -> dict[str, Any]:
        try:
            with range_based_freshness():
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
        if self._loop is None or self._async_queue is None:
            self._queue.put(line)
            return
        try:
            self._loop.call_soon_threadsafe(self._async_queue.put_nowait, line)
        except RuntimeError:
            pass

    def _work(self, job: _Job, query_id: str) -> None:
        try:
            with self._lock:
                if self._cancelled:
                    return
                self._active.add(query_id)
            with tags_context(team_id=self._team.pk, client_query_id=query_id):
                line = job()
            self._emit(line)
        finally:
            with self._lock:
                self._active.discard(query_id)
            connections.close_all()

    def _start(self) -> bool:
        if not self._jobs:
            return True
        self._admitted = _batch_slots.acquire(blocking=False)
        if not self._admitted:
            return False
        self._pool = ThreadPoolExecutor(max_workers=WORKERS_PER_BATCH, thread_name_prefix="dashboard-query-batch")
        context = copy_context()
        for _index, query_id, job in self._jobs:
            self._futures.append(self._pool.submit(context.copy().run, self._work, job, query_id))
        return True

    def _close(self, complete: bool) -> None:
        with self._lock:
            self._cancelled = True
            active = tuple(self._active)
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
        if not complete:
            # The client went away: stop what is still running in ClickHouse.
            for query_id in active:
                try:
                    cancel_query_on_cluster(team_id=self._team.pk, client_query_id=query_id)
                except Exception:
                    logger.exception("dashboard_v2_query_batch_cancel_failed", team_id=self._team.pk)
        if self._admitted:
            self._admitted = False
            for future in self._futures:
                future.cancel()
            # A running query keeps its thread after a disconnect, so the slot is freed when the last one ends.
            remaining = [future for future in self._futures if not future.done()]
            if not remaining:
                _batch_slots.release()
            else:
                pending = [len(remaining)]
                counter_lock = Lock()

                def done(_future: Future[None]) -> None:
                    with counter_lock:
                        pending[0] -= 1
                        last = pending[0] == 0
                    if last:
                        _batch_slots.release()

                for future in remaining:
                    future.add_done_callback(done)

    @staticmethod
    def _encode(line: dict[str, Any]) -> bytes:
        return SafeJSONRenderer().render(line) + b"\n"

    def _busy_lines(self) -> Iterator[bytes]:
        for index, _query_id, _job in self._jobs:
            yield self._encode({"i": index, "error": _BUSY})

    def stream(self) -> Iterator[bytes]:
        for line in self.ready:
            yield self._encode(line)
        if not self._start():
            yield from self._busy_lines()
            return
        complete = False
        try:
            remaining = len(self._jobs)
            while remaining:
                try:
                    line = self._queue.get(timeout=HEARTBEAT_SECONDS)
                except Empty:
                    # Proxies close a response that sends nothing for a while, which would end the batch early.
                    yield b"\n"
                    continue
                remaining -= 1
                yield self._encode(line)
            complete = True
        finally:
            self._close(complete)

    async def astream(self) -> AsyncIterator[bytes]:
        for line in self.ready:
            yield self._encode(line)
        self._loop = asyncio.get_running_loop()
        self._async_queue = asyncio.Queue()
        if not self._start():
            for chunk in self._busy_lines():
                yield chunk
            return
        complete = False
        try:
            remaining = len(self._jobs)
            while remaining:
                try:
                    line = await asyncio.wait_for(self._async_queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield b"\n"
                    continue
                remaining -= 1
                yield self._encode(line)
            complete = True
        finally:
            # A thread of its own: cancelling on the cluster blocks, and slow queries can fill the loop's executor.
            Thread(target=self._close, args=(complete,), daemon=True, name="dashboard-query-batch-close").start()
