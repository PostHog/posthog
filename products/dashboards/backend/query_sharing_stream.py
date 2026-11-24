import random
import asyncio
from collections.abc import AsyncGenerator, Callable, Generator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from queue import Queue
from threading import BoundedSemaphore, Event, Lock, Thread
from time import monotonic
from typing import Literal, NotRequired, TypedDict

from django.db import connections

import structlog
from prometheus_client import Counter

from posthog.hogql.query import hogql_execution_override
from posthog.hogql.query_stats import QueryStats, query_stats_scope

from posthog.clickhouse.cancel import cancel_query_on_cluster
from posthog.clickhouse.query_tagging import tags_context
from posthog.errors import QueryErrorCategory
from posthog.renderers import SafeJSONRenderer

from products.dashboards.backend.query_sharing import DashboardQuerySharing
from products.dashboards.backend.query_sharing_debug import DashboardQuerySharingDebug, SharingWorkDebug, sharing_debug

logger = structlog.get_logger(__name__)

WORKERS_PER_STREAM = 4
MAX_CONCURRENT_STREAMS = 8
_stream_slots = BoundedSemaphore(MAX_CONCURRENT_STREAMS)
# Rejected streams fall back to one request per tile, so a rising rejected count means the pod's slots are too few.
STREAM_ADMISSIONS = Counter(
    "posthog_dashboard_query_stream_admissions_total",
    "Dashboard query streams admitted or rejected for want of a stream slot",
    ["stream", "outcome"],
)
# A tile the organization's query limits turned away is retried, backing off up to the max delay, until this many
# seconds have passed since the stream's first rejection. One budget per stream, so a large board cannot hold a
# stream slot for a wait per tile. After that a tile is sent with its capacity error, and the client retries it.
CAPACITY_WAIT_SECONDS = 10.0
CAPACITY_RETRY_DELAY_SECONDS = 0.25
CAPACITY_RETRY_MAX_DELAY_SECONDS = 2.0


class DashboardQuerySharingTileEvent(TypedDict):
    type: Literal["tile"]
    tile: dict[str, object]
    debug: NotRequired[SharingWorkDebug]


class DashboardQuerySharingCachedEvent(TypedDict):
    type: Literal["cached"]
    tiles: list[dict[str, object]]
    pending: list[int]


class DashboardQuerySharingErrorEvent(TypedDict):
    type: Literal["error"]


class DashboardQuerySharingCompleteEvent(TypedDict):
    type: Literal["complete"]


type DashboardQuerySharingStreamEvent = (
    DashboardQuerySharingTileEvent
    | DashboardQuerySharingCachedEvent
    | DashboardQuerySharingErrorEvent
    | DashboardQuerySharingCompleteEvent
)


def _rejected_for_capacity(event: DashboardQuerySharingStreamEvent) -> bool:
    if event["type"] != "tile":
        return False
    insight = event["tile"].get("insight")
    query_status = insight.get("query_status") if isinstance(insight, dict) else None
    return isinstance(query_status, dict) and query_status.get("error_code") == QueryErrorCategory.RATE_LIMITED


class DashboardQuerySharingStream:
    def __init__(
        self,
        *,
        jobs: Sequence[Callable[[], DashboardQuerySharingStreamEvent]],
        team_id: int,
        query_id: str,
        debug_tile_ids: Sequence[int] = (),
        initial_events: Sequence[DashboardQuerySharingStreamEvent] = (),
        share_queries: bool = True,
        kind: Literal["board", "sharing"] = "sharing",
    ) -> None:
        self._jobs = jobs
        self._initial_events = initial_events
        self._share_queries = share_queries
        self._kind = kind
        # The board stream waits for the organization's query slots, as the per-tile path's client used to.
        self._wait_for_capacity = kind == "board"
        self._team_id = team_id
        self._query_id = query_id
        self._debug_tile_ids = debug_tile_ids
        self._context = copy_context()
        self._sharing = DashboardQuerySharing()
        self._queue: Queue[DashboardQuerySharingStreamEvent] = Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_queue: asyncio.Queue[DashboardQuerySharingStreamEvent] | None = None
        self._pool: ThreadPoolExecutor | None = None
        self._futures: list[Future[None]] = []
        self._slots = _stream_slots
        self._unfinished_workers = 0
        self._active: set[str] = set()
        self._lock = Lock()
        self._admitted = False
        self._capacity_deadline: float | None = None
        self.closed = Event()

    def _emit(self, event: DashboardQuerySharingStreamEvent) -> None:
        if self._loop is None or self._async_queue is None:
            self._queue.put(event)
            return
        try:
            self._loop.call_soon_threadsafe(self._async_queue.put_nowait, event)
        except RuntimeError:
            pass

    def _run(self, job: Callable[[], DashboardQuerySharingStreamEvent], query_id: str, tile_id: int | None) -> None:
        token = hogql_execution_override.set(self._sharing.execute if self._share_queries else None)
        debug = DashboardQuerySharingDebug(tile_id) if tile_id is not None else None
        debug_token = sharing_debug.set(debug)
        stats: QueryStats | None = None
        try:
            with self._lock:
                if self._sharing.cancelled.is_set():
                    return
                self._active.add(query_id)
            with tags_context(team_id=self._team_id, client_query_id=query_id):
                if debug:
                    with query_stats_scope() as stats:
                        event = self._run_job(job)
                else:
                    event = self._run_job(job)
            if event is None:
                return
            if debug and stats and event["type"] == "tile":
                # Keep diagnostics on the transport envelope, outside the independently cached tile results.
                event["debug"] = {
                    "executions": debug.executions,
                    "truncated": debug.truncated,
                    "query_count": stats.query_count,
                    "rows_read": stats.rows_read,
                    "duration_ms": stats.duration_ms,
                }
            self._emit(event)
        except Exception:
            self._emit({"type": "error"})
        finally:
            with self._lock:
                self._active.discard(query_id)
            hogql_execution_override.reset(token)
            sharing_debug.reset(debug_token)
            connections.close_all()

    def _capacity_wait_left(self) -> bool:
        with self._lock:
            if self._capacity_deadline is None:
                self._capacity_deadline = monotonic() + CAPACITY_WAIT_SECONDS
            return monotonic() < self._capacity_deadline

    def _run_job(self, job: Callable[[], DashboardQuerySharingStreamEvent]) -> DashboardQuerySharingStreamEvent | None:
        event = job()
        delay = CAPACITY_RETRY_DELAY_SECONDS
        while self._wait_for_capacity and _rejected_for_capacity(event) and self._capacity_wait_left():
            # Don't hold the tile's database connections idle through the wait.
            connections.close_all()
            if self._sharing.cancelled.wait(random.uniform(delay / 2, delay)):
                return None
            event = job()
            delay = min(delay * 2, CAPACITY_RETRY_MAX_DELAY_SECONDS)
        return event

    def _start(self) -> bool:
        self._slots = _stream_slots
        self._admitted = self._slots.acquire(blocking=False)
        STREAM_ADMISSIONS.labels(stream=self._kind, outcome="admitted" if self._admitted else "rejected").inc()
        if not self._admitted:
            return False
        try:
            self._pool = ThreadPoolExecutor(max_workers=WORKERS_PER_STREAM, thread_name_prefix="dashboard-sharing")
            for index, job in enumerate(self._jobs):
                future = self._pool.submit(
                    self._context.copy().run,
                    self._run,
                    job,
                    f"{self._query_id}-tile-{index}-",
                    self._debug_tile_ids[index] if self._debug_tile_ids else None,
                )
                self._futures.append(future)
        except Exception:
            logger.exception("Failed to start dashboard query sharing workers")
            self._close(complete=False)
            return False
        return True

    def _worker_finished(self, _future: Future[None]) -> None:
        with self._lock:
            self._unfinished_workers -= 1
            release = self._unfinished_workers == 0 and self._admitted
            if release:
                self._admitted = False
        if release:
            self._slots.release()

    def _release_slot_when_workers_finish(self) -> None:
        # A running tile keeps its thread and database connection after a disconnect, so the slot stays taken until it ends.
        with self._lock:
            self._unfinished_workers = len(self._futures)
            release = not self._futures and self._admitted
            if release:
                self._admitted = False
        if release:
            self._slots.release()
        for future in self._futures:
            future.add_done_callback(self._worker_finished)

    def _close(self, complete: bool) -> None:
        try:
            with self._lock:
                self._sharing.cancel()
                active = tuple(self._active)
            self._emit({"type": "error"})
            if self._pool:
                self._pool.shutdown(wait=False, cancel_futures=True)
            if not complete:
                for query_id in active:
                    try:
                        cancel_query_on_cluster(team_id=self._team_id, client_query_id=query_id)
                    except Exception:
                        logger.exception("Failed to cancel dashboard query sharing execution")
        finally:
            if self._admitted:
                self._release_slot_when_workers_finish()
            self.closed.set()

    @staticmethod
    def _encode(event: DashboardQuerySharingStreamEvent) -> bytes:
        return b"data: " + SafeJSONRenderer().render(event) + b"\n\n"

    def stream(self) -> Generator[bytes]:
        complete = False
        for event in self._initial_events:
            yield self._encode(event)
        if self._jobs and not self._start():
            yield self._encode({"type": "error"})
            return
        try:
            for _ in self._jobs:
                yield self._encode(self._queue.get())
            complete = True
            yield self._encode({"type": "complete"})
        finally:
            self._close(complete)

    async def astream(self) -> AsyncGenerator[bytes]:
        complete = False
        self._loop = asyncio.get_running_loop()
        self._async_queue = asyncio.Queue()
        for event in self._initial_events:
            yield self._encode(event)
        if self._jobs and not self._start():
            yield self._encode({"type": "error"})
            return
        try:
            for _ in self._jobs:
                yield self._encode(await self._async_queue.get())
            complete = True
            yield self._encode({"type": "complete"})
        finally:
            # A dedicated thread, because slow tile queries can occupy every thread of the loop's default executor.
            Thread(target=self._close, args=(complete,), daemon=True, name="dashboard-sharing-close").start()
