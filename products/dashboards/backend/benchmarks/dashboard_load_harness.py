"""
Client model and mocked compute backend for the dashboard benchmarks. No browser, no ClickHouse.

The scorecard (`dashboard_v2_scorecard.py`) sends every tile request through the real query runner
(`get_query_runner(...).run()`), so the real cache, limiters and flag checks decide what happens.
This module supplies the parts around that:

- `MockBackend`: replaces only the ClickHouse/Snuffle compute (`_calculate`) with a lognormal sleep
  behind a bounded semaphore, and counts every compute.
- `TileQueue` and `AutoRefreshTab`: the browser's request pattern, modelled on `dashboardLogic.tsx`
  (4 tile requests in flight per tab, 10 s auto refresh, a tile skipped while it is still pending).
- `run_board_load`: a first load of a board through the same client queue.

See README.md for what is real and what is mocked.
"""

import math
import time
import random
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from queue import Queue
from typing import Optional

# Mirrors frontend/src/scenes/dashboard/dashboardLogic.tsx
TILE_REFRESH_CONCURRENCY = 4
AUTO_REFRESH_INTERVAL_S = 10
# Tiles a viewer sees without scrolling. Matches the first-screen size in the visible-tiles change (#138169).
VISIBLE_TILES = 12

TileRequest = Callable[[int], str]  # tile index -> outcome: ok | rejected | error


@dataclass(frozen=False)
class MockBackend:
    """The mocked ClickHouse / Snuffle boundary: one compute is a lognormal sleep under a shared capacity."""

    capacity: int = 24
    metrics_median_ms: float = 600.0
    analytics_median_ms: float = 350.0
    logs_median_ms: float = 400.0
    sigma: float = 0.5
    seed: int = 7
    _sem: threading.Semaphore = field(init=False)
    _rng: random.Random = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    calls: Counter = field(default_factory=Counter)

    def __post_init__(self) -> None:
        self._sem = threading.Semaphore(self.capacity)
        self._rng = random.Random(self.seed)

    def compute(self, kind: str) -> None:
        median = {
            "metrics": self.metrics_median_ms,
            "analytics": self.analytics_median_ms,
            "logs": self.logs_median_ms,
        }[kind]
        with self._lock:
            self.calls[kind] += 1
            ms = self._rng.lognormvariate(math.log(median), self.sigma)
        with self._sem:
            time.sleep(ms / 1000)


@dataclass(frozen=True)
class Sample:
    latency_ms: float
    outcome: str


class TileQueue:
    """Client TaskQueue: at most `concurrency` tile requests in flight per dashboard tab."""

    def __init__(
        self, concurrency: int = TILE_REFRESH_CONCURRENCY, on_worker_exit: Optional[Callable[[], None]] = None
    ):
        self.q: Queue[Optional[Callable[[], None]]] = Queue()
        self._on_worker_exit = on_worker_exit
        self.threads = [threading.Thread(target=self._run, daemon=True) for _ in range(concurrency)]
        for t in self.threads:
            t.start()

    def _run(self) -> None:
        try:
            while True:
                task = self.q.get()
                if task is None:
                    return
                task()
        finally:
            if self._on_worker_exit is not None:
                self._on_worker_exit()

    def submit(self, task: Callable[[], None]) -> None:
        self.q.put(task)

    def stop(self) -> None:
        for _ in self.threads:
            self.q.put(None)
        for t in self.threads:
            t.join(timeout=60)


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(len(s) - 1, math.ceil(p / 100 * len(s)) - 1)], 1)


def summarize(samples: list[Sample]) -> dict:
    ok = [s.latency_ms for s in samples if s.outcome == "ok"]
    return {
        "requests": len(samples),
        "rejected": sum(1 for s in samples if s.outcome == "rejected"),
        "errors": sum(1 for s in samples if s.outcome == "error"),
        "ok": len(ok),
        "p50_ms": pct(ok, 50),
        "p95_ms": pct(ok, 95),
    }


class AutoRefreshTab:
    """One open dashboard with auto refresh: every interval, every tile not already queued refreshes."""

    def __init__(
        self,
        request: TileRequest,
        tiles: int,
        interval_s: float,
        on_worker_exit: Optional[Callable[[], None]] = None,
    ) -> None:
        self.request, self.tiles, self.interval_s = request, tiles, interval_s
        self.queue = TileQueue(on_worker_exit=on_worker_exit)
        self.samples: list[Sample] = []
        self._lock = threading.Lock()
        self._pending: set[int] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _refresh_tile(self, tile: int, enqueued_at: float) -> None:
        outcome = self.request(tile)
        end = time.monotonic()
        with self._lock:
            self._pending.discard(tile)
            # Latency spans queue wait + request, which is what the viewer waits for.
            self.samples.append(Sample((end - enqueued_at) * 1000, outcome))

    def _cycle(self) -> None:
        now = time.monotonic()
        for tile in range(self.tiles):
            with self._lock:
                if tile in self._pending:
                    continue
                self._pending.add(tile)
            self.queue.submit(partial(self._refresh_tile, tile, now))

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._cycle()
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        self._thread.start()

    def stop_refreshing(self) -> None:
        self._stop.set()
        self._thread.join()

    def stop(self) -> None:
        self.stop_refreshing()
        self.queue.stop()


def run_auto_refresh(tabs: list[AutoRefreshTab], duration_s: float) -> list[dict]:
    for tab in tabs:
        tab.start()
    time.sleep(duration_s)
    # Stop every refresh loop before draining any queue, so no tab keeps cycling while another drains.
    for tab in tabs:
        tab.stop_refreshing()
    for tab in tabs:
        tab.queue.stop()
    return [summarize(tab.samples) for tab in tabs]


BOARD_LOAD_TIMEOUT_S = 900


def run_board_load(
    request: TileRequest,
    requested_tiles: int,
    first_screen: int = VISIBLE_TILES,
    on_worker_exit: Optional[Callable[[], None]] = None,
) -> dict:
    """First load: the client queues one request per requested tile, in layout order, 4 at a time."""
    queue = TileQueue(on_worker_exit=on_worker_exit)
    lock = threading.Lock()
    done = threading.Event()
    first_screen_done = threading.Event()
    remaining = [requested_tiles]
    first_screen_remaining = [min(first_screen, requested_tiles)]
    outcomes: Counter = Counter()
    start = time.monotonic()
    first_screen_ms: list[float] = []

    def task(i: int) -> None:
        outcome = request(i)
        with lock:
            outcomes[outcome] += 1
            if i < first_screen:
                first_screen_remaining[0] -= 1
                if first_screen_remaining[0] == 0:
                    first_screen_ms.append((time.monotonic() - start) * 1000)
                    first_screen_done.set()
            remaining[0] -= 1
            if remaining[0] == 0:
                done.set()

    for i in range(requested_tiles):
        queue.submit(partial(task, i))
    settled = done.wait(timeout=BOARD_LOAD_TIMEOUT_S)
    total_ms = (time.monotonic() - start) * 1000
    queue.stop()
    if not settled:
        raise TimeoutError(
            f"board load did not settle within {BOARD_LOAD_TIMEOUT_S} s: {remaining[0]} of {requested_tiles} tiles pending"
        )
    return {
        "requested_tiles": requested_tiles,
        "outcomes": dict(outcomes),
        "first_screen_ms": round(first_screen_ms[0], 1) if first_screen_ms else None,
        "settled_ms": round(total_ms, 1),
    }
