import asyncio
from collections.abc import AsyncGenerator, Callable, Generator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from queue import Queue
from threading import Lock
from typing import Literal, TypedDict

from django.db import connections

import structlog

from posthog.hogql.query import hogql_execution_override

from posthog.clickhouse.cancel import cancel_query_on_cluster
from posthog.clickhouse.query_tagging import tags_context
from posthog.renderers import SafeJSONRenderer

from products.dashboards.backend.query_sharing import DashboardQuerySharing

logger = structlog.get_logger(__name__)


class DashboardQuerySharingTileEvent(TypedDict):
    type: Literal["tile"]
    tile: dict[str, object]


class DashboardQuerySharingErrorEvent(TypedDict):
    type: Literal["error"]


class DashboardQuerySharingCompleteEvent(TypedDict):
    type: Literal["complete"]


type DashboardQuerySharingStreamEvent = (
    DashboardQuerySharingTileEvent | DashboardQuerySharingErrorEvent | DashboardQuerySharingCompleteEvent
)


class DashboardQuerySharingStream:
    def __init__(
        self, *, jobs: Sequence[Callable[[], DashboardQuerySharingStreamEvent]], team_id: int, query_id: str
    ) -> None:
        self._jobs = jobs
        self._team_id = team_id
        self._query_id = query_id
        self._context = copy_context()
        self._sharing = DashboardQuerySharing()
        self._queue: Queue[DashboardQuerySharingStreamEvent] = Queue()
        self._pool: ThreadPoolExecutor | None = None
        self._active: set[str] = set()
        self._lock = Lock()

    def _run(self, job: Callable[[], DashboardQuerySharingStreamEvent], query_id: str) -> None:
        token = hogql_execution_override.set(self._sharing.execute)
        try:
            with self._lock:
                if self._sharing.cancelled.is_set():
                    return
                self._active.add(query_id)
            with tags_context(team_id=self._team_id, client_query_id=query_id):
                self._queue.put(job())
        except Exception:
            self._queue.put({"type": "error"})
        finally:
            with self._lock:
                self._active.discard(query_id)
            hogql_execution_override.reset(token)
            connections.close_all()

    def _start(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dashboard-sharing")
        for index, job in enumerate(self._jobs):
            self._pool.submit(self._context.copy().run, self._run, job, f"{self._query_id}-tile-{index}-")

    def _close(self, complete: bool) -> None:
        with self._lock:
            self._sharing.cancel()
            active = tuple(self._active)
        self._queue.put({"type": "error"})
        if self._pool:
            self._pool.shutdown(wait=False, cancel_futures=True)
        if not complete:
            for query_id in active:
                try:
                    cancel_query_on_cluster(team_id=self._team_id, client_query_id=query_id)
                except Exception:
                    logger.exception("Failed to cancel dashboard query sharing execution")

    @staticmethod
    def _encode(event: DashboardQuerySharingStreamEvent) -> bytes:
        return b"data: " + SafeJSONRenderer().render(event) + b"\n\n"

    def stream(self) -> Generator[bytes]:
        complete = False
        self._start()
        try:
            for _ in self._jobs:
                yield self._encode(self._queue.get())
            complete = True
            yield self._encode({"type": "complete"})
        finally:
            self._close(complete)

    async def astream(self) -> AsyncGenerator[bytes]:
        complete = False
        self._start()
        try:
            for _ in self._jobs:
                yield self._encode(await asyncio.to_thread(self._queue.get))
            complete = True
            yield self._encode({"type": "complete"})
        finally:
            await asyncio.to_thread(self._close, complete)
