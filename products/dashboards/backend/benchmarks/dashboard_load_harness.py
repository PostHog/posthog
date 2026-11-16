"""
Backend load harness for APM-style dashboards. No browser, no Django server, no ClickHouse.

It replays the request pattern of the dashboard frontend against the REAL server-side concurrency
limiters (`get_app_org_rate_limiter`, `get_app_dashboard_queries_rate_limiter`, backed by the local Redis)
and a MOCKED ClickHouse/Snuffle boundary (a bounded-capacity sleep). See README.md for what is real vs mocked.

Run (needs local Redis on the default port, nothing else):

    DEBUG=1 PYTHONPATH=. DJANGO_SETTINGS_MODULE=posthog.settings \
        python products/dashboards/backend/benchmarks/dashboard_load_harness.py [--quick]

Last stdout lines: one JSON object with every metric, then `SCORE=<n>` (lower is better).
"""

import os
import sys
import json
import math
import time
import random
import argparse
import threading
import statistics
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from queue import Queue
from typing import Optional

os.environ.setdefault("DEBUG", "1")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

import django  # noqa: E402

django.setup()

from posthog.clickhouse.client.limit import (  # noqa: E402
    ConcurrencyLimitExceeded,
    get_app_dashboard_queries_rate_limiter,
    get_app_org_rate_limiter,
)

# Mirrors frontend/src/scenes/dashboard/dashboardLogic.tsx
TILE_REFRESH_CONCURRENCY = 4
AUTO_REFRESH_INTERVAL_S = 10
# Tiles a viewer sees without scrolling; used by `--load-mode visible`
VISIBLE_TILES = 12


@dataclass
class Mock:
    """The mocked ClickHouse / Snuffle boundary."""

    capacity: int = 24  # concurrent queries the backend can serve before they queue
    metrics_median_ms: float = 600.0
    analytics_median_ms: float = 350.0
    cached_read_ms: float = 15.0
    sigma: float = 0.5
    seed: int = 7
    _sem: threading.Semaphore = field(init=False)
    _rng: random.Random = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    calls: Counter = field(default_factory=Counter)

    def __post_init__(self) -> None:
        self._sem = threading.Semaphore(self.capacity)
        self._rng = random.Random(self.seed)

    def query(self, kind: str) -> None:
        median = self.metrics_median_ms if kind == "metrics" else self.analytics_median_ms
        with self._lock:
            self.calls[kind] += 1
            ms = self._rng.lognormvariate(math.log(median), self.sigma)
        with self._sem:
            time.sleep(ms / 1000)


@dataclass
class Sample:
    kind: str
    latency_ms: float
    outcome: str  # ok | rejected | error
    at: float


class Server:
    """What one tile request does on the server: limiters (real) then ClickHouse (mock)."""

    def __init__(self, mock: Mock, org_id: str, workers: int) -> None:
        self.mock = mock
        self.org_id = org_id
        self._workers = threading.Semaphore(workers)  # gunicorn threads
        self.org_limiter = get_app_org_rate_limiter()
        self.dash_limiter = get_app_dashboard_queries_rate_limiter()

    def tile_query(self, kind: str, dashboard_id: int, cached: bool = False) -> str:
        with self._workers:
            if cached:
                time.sleep(self.mock.cached_read_ms / 1000)
                return "ok"
            try:
                # Same nesting order as QueryRunner.run in posthog/hogql_queries/query_runner.py
                with (
                    self.org_limiter.run(org_id=self.org_id, team_id=1, is_api=False),
                    self.dash_limiter.run(org_id=self.org_id, dashboard_id=dashboard_id, team_id=1, is_api=False),
                ):
                    self.mock.query(kind)
            except ConcurrencyLimitExceeded:
                return "rejected"
            return "ok"


class TileQueue:
    """Client TaskQueue: at most TILE_REFRESH_CONCURRENCY in flight per dashboard tab."""

    def __init__(self, concurrency: int = TILE_REFRESH_CONCURRENCY) -> None:
        self.q: Queue[Optional[Callable[[], None]]] = Queue()
        self.threads = [threading.Thread(target=self._run, daemon=True) for _ in range(concurrency)]
        for t in self.threads:
            t.start()

    def _run(self) -> None:
        while True:
            task = self.q.get()
            if task is None:
                return
            task()

    def submit(self, task: Callable[[], None]) -> None:
        self.q.put(task)

    def stop(self) -> None:
        for _ in self.threads:
            self.q.put(None)
        for t in self.threads:
            t.join(timeout=30)


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(len(s) - 1, math.ceil(p / 100 * len(s)) - 1)], 1)


class AutoRefreshTab:
    """One open dashboard with auto refresh: every interval every tile that is not already queued refreshes (force_blocking)."""

    def __init__(self, server: Server, kind: str, tiles: int, dashboard_id: int, interval_s: float) -> None:
        self.server, self.kind, self.tiles, self.dashboard_id, self.interval_s = (
            server,
            kind,
            tiles,
            dashboard_id,
            interval_s,
        )
        self.queue = TileQueue()
        self.samples: list[Sample] = []
        self._lock = threading.Lock()
        self._pending: set[int] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _refresh_tile(self, tile: int, enqueued_at: float) -> None:
        outcome = self.server.tile_query(self.kind, self.dashboard_id)
        end = time.monotonic()
        with self._lock:
            self._pending.discard(tile)
            # Latency spans queue wait + request, which is what the viewer waits for.
            self.samples.append(Sample(self.kind, (end - enqueued_at) * 1000, outcome, end))

    def _cycle(self) -> None:
        now = time.monotonic()
        for tile in range(self.tiles):
            with self._lock:
                if tile in self._pending:
                    continue
                self._pending.add(tile)
            self.queue.submit(lambda t=tile, n=now: self._refresh_tile(t, n))

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._cycle()
            self._stop.wait(self.interval_s)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()
        self.queue.stop()


def summarize(samples: list[Sample]) -> dict:
    ok = [s.latency_ms for s in samples if s.outcome == "ok"]
    return {
        "requests": len(samples),
        "rejected": sum(1 for s in samples if s.outcome == "rejected"),
        "ok": len(ok),
        "p50_ms": pct(ok, 50),
        "p95_ms": pct(ok, 95),
    }


def run_refresh(server: Server, args: argparse.Namespace) -> dict:
    """M1 + M3: APM board auto refreshing while an analytics board in the same org does the same."""
    mock = server.mock
    mock.calls.clear()
    apm = AutoRefreshTab(server, "metrics", args.apm_tiles, dashboard_id=101, interval_s=args.interval)
    analytics = AutoRefreshTab(server, "analytics", args.analytics_tiles, dashboard_id=202, interval_s=args.interval)
    apm.start()
    analytics.start()
    time.sleep(args.duration)
    apm.stop()
    analytics.stop()
    m1 = summarize(apm.samples)
    m3 = summarize(analytics.samples)
    return {
        "m1": {**m1, "events_queries_triggered": mock.calls["analytics"] if args.count_analytics_in_m1 else 0},
        "m3": m3,
        "backend_calls": dict(mock.calls),
    }


def isolation_baseline(server: Server, args: argparse.Namespace) -> dict:
    """The analytics board alone, so M3 can be read as a delta."""
    analytics = AutoRefreshTab(server, "analytics", args.analytics_tiles, dashboard_id=202, interval_s=args.interval)
    analytics.start()
    time.sleep(min(args.duration, 30))
    analytics.stop()
    return summarize(analytics.samples)


def run_load(server: Server, tiles: int, args: argparse.Namespace) -> dict:
    """M2: first load. The client dispatches one tile request per tile through the 4-wide queue.

    Cached paint: the first cached tile response. Fully loaded: every tile resolved (cold cache, so each
    tile reaches the mock backend).
    """
    requested = VISIBLE_TILES if args.load_mode == "visible" else tiles
    requested = min(requested, tiles)
    server.mock.calls.clear()
    queue = TileQueue()
    done = threading.Event()
    remaining = [requested]
    lock = threading.Lock()
    start = time.monotonic()
    first_paint: list[float] = []

    def tile_task(i: int) -> None:
        if i == 0:
            outcome = server.tile_query("metrics", 303, cached=True)
            first_paint.append((time.monotonic() - start) * 1000)
            del outcome
        server.tile_query("metrics", 303)
        with lock:
            remaining[0] -= 1
            if remaining[0] == 0:
                done.set()

    for i in range(requested):
        queue.submit(lambda i=i: tile_task(i))
    done.wait(timeout=300)
    total_ms = (time.monotonic() - start) * 1000
    queue.stop()
    return {
        "tiles_on_board": tiles,
        "tile_queries_issued": server.mock.calls["metrics"],
        "first_paint_ms": round(first_paint[0], 1) if first_paint else None,
        "fully_loaded_ms": round(total_ms, 1),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--quick", action="store_true", help="20s refresh window, 3 load runs (smoke test)")
    p.add_argument("--duration", type=float, default=120.0, help="seconds of auto refresh for M1/M3")
    p.add_argument("--interval", type=float, default=AUTO_REFRESH_INTERVAL_S)
    p.add_argument("--apm-tiles", type=int, default=50)
    p.add_argument("--analytics-tiles", type=int, default=12)
    p.add_argument("--load-runs", type=int, default=10, help="N runs for the M2 p95")
    p.add_argument("--load-mode", choices=["all", "visible"], default="all", help="which tiles the board load requests")
    p.add_argument("--server-workers", type=int, default=32)
    p.add_argument("--mock-capacity", type=int, default=24)
    p.add_argument(
        "--count-analytics-in-m1", action="store_true", help="report analytics-kind backend calls as M1 events queries"
    )
    p.add_argument("--out", help="also write the JSON here")
    args = p.parse_args()
    if args.quick:
        args.duration, args.load_runs = 20.0, 3

    org_id = f"bench-{random.randrange(10**9)}"
    mock = Mock(capacity=args.mock_capacity)
    server = Server(mock, org_id, args.server_workers)

    results: dict = {"config": {k: v for k, v in vars(args).items() if k != "out"}}
    try:
        results["m3_alone"] = isolation_baseline(server, args)
        refresh = run_refresh(server, args)
        results.update(refresh)
        loads50 = [run_load(server, 50, args) for _ in range(args.load_runs)]
        results["m2_50"] = {
            "first_paint_p95_ms": pct([r["first_paint_ms"] for r in loads50 if r["first_paint_ms"] is not None], 95),
            "fully_loaded_p95_ms": pct([r["fully_loaded_ms"] for r in loads50], 95),
            "tile_queries_issued": statistics.median(r["tile_queries_issued"] for r in loads50),
        }
        results["m2_300"] = run_load(server, 300, args)
    finally:
        r = server.org_limiter.redis_client
        for key in (f"app:query:per-org:{org_id}", f"app:dashboard_query:per-org:{org_id}"):
            r.delete(key)

    m1, m3 = results["m1"], results["m3"]
    m3_alone_p95 = results["m3_alone"]["p95_ms"]
    # Lower is better. Rejections dominate; latency terms are 1 point per 100ms.
    score = (
        m1["rejected"]
        + m3["rejected"]
        + m1["events_queries_triggered"]
        + m1["p95_ms"] / 100
        + max(0.0, m3["p95_ms"] - m3_alone_p95) / 100
        + results["m2_50"]["fully_loaded_p95_ms"] / 1000
        + results["m2_300"]["tile_queries_issued"] / 10
    )
    results["score_terms"] = (
        "m1.rejected + m3.rejected + m1.events_queries + m1.p95_ms/100 + (m3.p95-m3_alone.p95)/100 + m2_50.fully_loaded_p95_ms/1000 + m2_300.tile_queries/10"
    )
    line = json.dumps(results, sort_keys=True)
    if args.out:
        with open(args.out, "w") as f:
            f.write(line + "\n")
    sys.stdout.write(line + "\n")
    sys.stdout.write(f"SCORE={score:.2f}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
