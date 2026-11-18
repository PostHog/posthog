"""
Dashboards v2 before/after scenarios (roadmap: https://github.com/PostHog/posthog/issues/138125).

Each scenario runs once with `dashboard-v2` forced off (today's behaviour) and once forced on. Requests go
through the real server code: `get_query_runner(...).run()`, the insight and dashboard endpoints through
the Django test client, the logs widget, and the cache warming scheduler. Only the ClickHouse/Snuffle
compute (`_calculate`) is replaced, by `MockBackend`. Needs a Django test database, so it runs under
pytest; `dashboard_v2_scorecard.py` is the command line entry point.

A step whose code is not on this branch yet is reported as "not merged yet", and its "after" arm is
skipped. Each step's marker is in `STEPS`.
"""

import os
import sys
import json
import time
import random
import inspect
import threading
import statistics
import subprocess
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import time_machine
from unittest.mock import patch

from django.conf import settings
from django.db import connection, connections
from django.test import Client
from django.test.utils import CaptureQueriesContext, override_settings

import redis as redis_lib

from posthog.schema import (
    EventsNode,
    LogsQueryResponse,
    MetricsQuery,
    MetricsQueryClause,
    MetricsQueryResponse,
    TrendsQuery,
    TrendsQueryResponse,
)

from posthog import (
    permissions,
    redis as posthog_redis,
)
from posthog.caching import warming
from posthog.clickhouse.client import limit
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner
from posthog.models import Organization, Project, Team, User
from posthog.query_cache.freshness_index import update_target_age
from posthog.query_cache.read_history import record_read

from products.dashboards.backend.benchmarks.dashboard_load_harness import (
    AUTO_REFRESH_INTERVAL_S,
    VISIBLE_TILES,
    AutoRefreshTab,
    MockBackend,
    TileRequest,
    run_auto_refresh,
    run_board_load,
)
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.backend.presentation.views.dashboard import DashboardsViewSet
from products.dashboards.backend.test.benchmark_fixtures import create_insight_tiles
from products.dashboards.backend.widgets import logs_list
from products.logs.backend.facade.queries import LogsQueryRunner

DASHBOARD_V2_FLAG = "dashboard-v2"
# Flags a scenario needs on in both arms, so that only `dashboard-v2` differs between them.
PRECONDITION_FLAGS = frozenset({"metrics"})
NOT_MERGED = "not merged yet"


@dataclass(frozen=True)
class Step:
    key: str
    roadmap_step: str
    pr: str
    title: str
    merged: Callable[[], bool]


def _frontend_source_contains(relative_path: str, marker: str) -> bool:
    path = Path(settings.BASE_DIR) / relative_path
    return path.exists() and marker in path.read_text()


# Markers are names each PR adds. If a PR renames one before merging, update it here.
STEPS: dict[str, Step] = {
    step.key: step
    for step in (
        Step(
            key="batched_read",
            roadmap_step="1",
            pr="#138219",
            title="Read a board's cached tiles in one request",
            merged=lambda: hasattr(DashboardsViewSet, "cached_tiles"),
        ),
        Step(
            key="metrics_lane",
            roadmap_step="2",
            pr="#138146",
            title="Metrics tiles get their own query slots that wait",
            merged=lambda: hasattr(limit, "get_app_telemetry_queries_rate_limiter"),
        ),
        Step(
            key="visible_tiles",
            roadmap_step="2b",
            pr="#138169",
            title="Load and refresh only the tiles on screen (frontend)",
            merged=lambda: _frontend_source_contains(
                "frontend/src/scenes/dashboard/dashboardLogic.tsx", "splitOffscreenTiles"
            ),
        ),
        Step(
            key="read_tiles_warming",
            roadmap_step="3",
            pr="#138141",
            title="Only warm tiles that people read",
            merged=lambda: hasattr(warming, "DASHBOARD_V2_FLAG"),
        ),
        Step(
            key="logs_cache",
            roadmap_step="4",
            pr="#138142",
            title="Logs tiles hit the query cache",
            merged=lambda: "dashboard_v2" in inspect.getsource(logs_list),
        ),
    )
}


@dataclass(frozen=False)
class Config:
    quick: bool = False
    seed: int = 7
    repeats: int = 3
    arms: tuple[str, ...] = ("off", "on")
    measure_unmerged: bool = False
    scenarios: tuple[str, ...] = ("A", "B", "C", "D", "E")
    # A
    refresh_duration_s: float = 120.0
    analytics_alone_s: float = 30.0
    refresh_interval_s: float = AUTO_REFRESH_INTERVAL_S
    metrics_tiles: int = 50
    analytics_tiles: int = 12
    server_workers: int = 32
    backend_capacity: int = 24
    # B
    cached_tile_counts: tuple[int, ...] = (1, 5, 10, 20, 50)
    # C
    logs_viewers: int = 2
    logs_refreshes: int = 10
    logs_window_s: int = 60
    # D
    warming_stale_tiles: int = 20
    warming_read_tiles: int = 3
    # E
    large_board_tiles: int = 300

    @classmethod
    def quick_mode(cls, **overrides: Any) -> "Config":
        values: dict[str, Any] = {
            "quick": True,
            "repeats": 1,
            "refresh_duration_s": 20.0,
            "analytics_alone_s": 10.0,
            "cached_tile_counts": (1, 5, 20),
            "large_board_tiles": 60,
        }
        values.update(overrides)
        return cls(**values)


@dataclass(frozen=False)
class Metric:
    name: str
    unit: str
    better: str  # lower | higher
    before_runs: list[float] = field(default_factory=list)
    after_runs: list[float] = field(default_factory=list)


@dataclass(frozen=False)
class ScenarioResult:
    id: str
    title: str
    roadmap_step: str
    step_key: str
    modelled_client: bool
    metrics: list[Metric]
    after_status: str = "measured"


# ---- flag forcing -------------------------------------------------------------------------------


@contextmanager
def dashboard_v2(enabled: bool) -> Iterator[None]:
    """Force `dashboard-v2` through POSTHOG_FEATURE_FLAGS_FORCE_ENABLED's set, `_FORCE_ENABLED_FLAGS`.

    Modules that imported the set by name hold their own reference, so every holder is patched. Remote
    flag evaluation is pinned to False, so a local flag definition can't turn the "off" arm on.
    """
    original = permissions._FORCE_ENABLED_FLAGS
    base = (original | PRECONDITION_FLAGS) - {DASHBOARD_V2_FLAG}
    forced = base | {DASHBOARD_V2_FLAG} if enabled else base
    holders = []
    for module in list(sys.modules.values()):
        try:
            if getattr(module, "_FORCE_ENABLED_FLAGS", None) is original:
                holders.append(module)
        except Exception:
            continue
    with ExitStack() as stack:
        for module in holders:
            stack.enter_context(patch.object(module, "_FORCE_ENABLED_FLAGS", forced))
        stack.enter_context(patch("posthoganalytics.feature_enabled", return_value=False))
        yield


# ---- tenants and fixtures -----------------------------------------------------------------------


@dataclass(frozen=False)
class Tenant:
    organization: Organization
    team: Team
    user: User


_ids = random.SystemRandom()


def make_tenant(label: str) -> Tenant:
    """A fresh organization, project and team. The team id is random and high so Redis keys from other local runs can't collide."""
    organization = Organization.objects.create(name=f"dashboard-v2 bench {label}")
    team_id = _ids.randrange(1_500_000_000, 2_000_000_000)
    project = Project.objects.create(id=team_id, organization=organization)
    team = Team.objects.create(id=team_id, project=project, organization=organization, name=f"bench {label}")
    user = User.objects.create_and_join(organization, f"dv2-bench-{team_id}@example.com", None)
    return Tenant(organization=organization, team=team, user=user)


def _trends_query(i: int) -> TrendsQuery:
    return TrendsQuery(series=[EventsNode(event=f"bench_event_{i}")])


def _metrics_query(i: int) -> MetricsQuery:
    return MetricsQuery(clauses=[MetricsQueryClause(name="a", metricName=f"bench.metric.{i}")])


def _insight_tiles(tenant: Tenant, dashboard: Dashboard, count: int, offset: int = 0) -> list[DashboardTile]:
    queries = [
        (f"bench {i}", {"kind": "InsightVizNode", "source": _trends_query(i).model_dump(exclude_none=True)})
        for i in range(offset, offset + count)
    ]
    return create_insight_tiles(tenant.team, tenant.user, dashboard, queries)


@contextmanager
def mocked_compute(team: Team, backend: MockBackend) -> Iterator[None]:
    """Replace only `_calculate` (the ClickHouse/Snuffle work) of the runners the scenarios use."""
    trends_runner = type(get_query_runner(_trends_query(0), team))
    metrics_runner = type(get_query_runner(_metrics_query(0), team))

    def trends(_runner: Any) -> TrendsQueryResponse:
        backend.compute("analytics")
        return TrendsQueryResponse(results=[])

    def metrics(_runner: Any) -> MetricsQueryResponse:
        backend.compute("metrics")
        return MetricsQueryResponse(results=[])

    def logs(_runner: Any) -> LogsQueryResponse:
        backend.compute("logs")
        return LogsQueryResponse(
            results=[
                {"uuid": "0196e9ab-0000-0000-0000-000000000000", "timestamp": "2026-01-01T00:00:00Z", "body": "x"}
            ],
            hasMore=False,
        )

    with (
        patch.object(trends_runner, "_calculate", trends),
        patch.object(metrics_runner, "_calculate", metrics),
        patch.object(LogsQueryRunner, "_calculate", logs),
    ):
        yield


@contextmanager
def real_redis() -> Iterator[None]:
    """pytest sets TEST, which swaps Redis for FakeRedis and the Django caches for LocMemCache.
    Point both back at the local Redis so limiter and cache timings include real round trips."""
    clients: dict[tuple[str, float, float], redis_lib.Redis] = {}

    def get_client(
        redis_url: Optional[str] = None,
        *,
        socket_timeout: Optional[float] = None,
        socket_connect_timeout: Optional[float] = None,
    ) -> redis_lib.Redis:
        # Same timeouts and per-call overrides as `posthog.redis.get_client`, minus its TEST switch.
        key = (
            redis_url or settings.REDIS_URL,
            settings.REDIS_SOCKET_TIMEOUT_SECONDS if socket_timeout is None else socket_timeout,
            settings.REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS if socket_connect_timeout is None else socket_connect_timeout,
        )
        if key not in clients:
            clients[key] = redis_lib.from_url(key[0], db=0, socket_timeout=key[1], socket_connect_timeout=key[2])
        return clients[key]

    client = get_client()
    client.ping()
    redis_cache = {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": settings.REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        "KEY_PREFIX": "dv2bench",
    }
    caches = {**settings.CACHES, **dict.fromkeys(("default", "query_cache"), redis_cache)}
    with (
        patch.object(posthog_redis, "get_client", get_client),
        patch.object(limit.RateLimit, "redis_client", client),
        override_settings(CACHES=caches),
    ):
        yield


@contextmanager
def live_limiters(organization: Organization) -> Iterator[None]:
    """The app limiters skip themselves when TEST is set. Lift that so the real Redis limiters apply."""
    try:
        with patch.object(limit, "TEST", False):
            yield
    finally:
        redis = limit.get_app_org_rate_limiter().redis_client
        for kind in ("query", "dashboard_query", "telemetry_query"):
            redis.delete(f"app:{kind}:per-org:{organization.id}")


class RunnerServer:
    """One tile request on the server: `get_query_runner(...).run()` behind a fixed pool of worker threads."""

    def __init__(self, tenant: Tenant, workers: int) -> None:
        self.tenant = tenant
        self._workers = threading.Semaphore(workers)
        self.errors: Counter = Counter()

    def tile_request(self, kind: str, dashboard_id: int) -> TileRequest:
        build = _metrics_query if kind == "metrics" else _trends_query

        def request(tile: int) -> str:
            with self._workers:
                team, user = self.tenant.team, self.tenant.user
                try:
                    runner = get_query_runner(build(tile), team, user=user)
                    # Auto refresh asks for fresh results (`force_blocking`), so every request computes.
                    runner.run(
                        execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                        user=user,
                        dashboard_id=dashboard_id,
                    )
                except ConcurrencyLimitExceeded:
                    return "rejected"
                except Exception as exc:
                    self.errors[f"{type(exc).__name__}: {str(exc)[:120]}"] += 1
                    return "error"
                return "ok"

        return request


def _close_thread_connections() -> None:
    connections.close_all()


# ---- scenarios ----------------------------------------------------------------------------------


def scenario_a(cfg: Config, enabled: bool, run: int) -> dict[str, float]:
    """A metrics board auto refreshing next to an analytics board in the same organization."""
    tenant = make_tenant(f"A-{run}")
    metrics_board = Dashboard.objects.create(team=tenant.team, name="metrics board")
    analytics_board = Dashboard.objects.create(team=tenant.team, name="analytics board")
    backend = MockBackend(capacity=cfg.backend_capacity, seed=cfg.seed + run)
    server = RunnerServer(tenant, cfg.server_workers)
    interval = cfg.refresh_interval_s
    with dashboard_v2(enabled), mocked_compute(tenant.team, backend), live_limiters(tenant.organization):
        (alone,) = run_auto_refresh(
            [
                AutoRefreshTab(
                    server.tile_request("analytics", analytics_board.id),
                    cfg.analytics_tiles,
                    interval,
                    on_worker_exit=_close_thread_connections,
                )
            ],
            cfg.analytics_alone_s,
        )
        metrics, analytics = run_auto_refresh(
            [
                AutoRefreshTab(
                    server.tile_request("metrics", metrics_board.id),
                    cfg.metrics_tiles,
                    interval,
                    on_worker_exit=_close_thread_connections,
                ),
                AutoRefreshTab(
                    server.tile_request("analytics", analytics_board.id),
                    cfg.analytics_tiles,
                    interval,
                    on_worker_exit=_close_thread_connections,
                ),
            ],
            cfg.refresh_duration_s,
        )
    if server.errors:
        raise RuntimeError(f"scenario A tile requests failed unexpectedly: {dict(server.errors)}")
    return {
        "metrics_rejected": metrics["rejected"],
        "analytics_rejected": analytics["rejected"],
        "metrics_p95_ms": metrics["p95_ms"],
        "analytics_p95_ms": analytics["p95_ms"],
        "analytics_slowdown_ms": round(analytics["p95_ms"] - alone["p95_ms"], 1),
        "tiles_served": metrics["ok"] + analytics["ok"],
    }


def _warm_per_tile(client: Client, tenant: Tenant, dashboard: Dashboard, tiles: list[DashboardTile]) -> None:
    for tile in tiles:
        response = client.get(
            f"/api/projects/{tenant.team.id}/insights/{tile.insight_id}/",
            {"from_dashboard": str(dashboard.id), "refresh": "blocking"},
        )
        if response.status_code != 200:
            raise RuntimeError(f"warming tile {tile.id} failed: {response.status_code} {response.content[:300]!r}")


def _read_per_tile(client: Client, tenant: Tenant, dashboard: Dashboard, tiles: list[DashboardTile]) -> None:
    for tile in tiles:
        # What the dashboard sends for each tile on load (`getInsightWithRetry` with `blocking`).
        response = client.get(
            f"/api/projects/{tenant.team.id}/insights/{tile.insight_id}/",
            {"from_dashboard": str(dashboard.id), "refresh": "blocking"},
        )
        body = response.json()
        if response.status_code != 200 or not body.get("is_cached"):
            raise RuntimeError(f"per-tile read of tile {tile.id} was not a cache hit: {response.status_code}")


def _read_batched(client: Client, tenant: Tenant, dashboard: Dashboard, tiles: list[DashboardTile]) -> None:
    response = client.get(
        f"/api/projects/{tenant.team.id}/dashboards/{dashboard.id}/cached_tiles/",
        {"tile_ids": ",".join(str(tile.id) for tile in tiles)},
    )
    if response.status_code != 200:
        raise RuntimeError(f"batched read failed: {response.status_code} {response.content[:300]!r}")
    statuses = Counter(entry["status"] for entry in response.json()["results"])
    if statuses != Counter({"hit": len(tiles)}):
        raise RuntimeError(f"batched read was not all hits: {dict(statuses)}")


def scenario_b(cfg: Config, enabled: bool, run: int) -> dict[str, float]:
    """A board of N cached tiles: N per-tile insight reads (today) vs one batched read."""
    tenant = make_tenant(f"B-{run}")
    backend = MockBackend(capacity=cfg.backend_capacity, seed=cfg.seed + run)
    client = Client()
    client.force_login(tenant.user)
    use_batched = enabled and STEPS["batched_read"].merged()
    out: dict[str, float] = {}
    with dashboard_v2(enabled), mocked_compute(tenant.team, backend):
        for n in cfg.cached_tile_counts:
            dashboard = Dashboard.objects.create(team=tenant.team, name=f"cached {n}")
            tiles = _insight_tiles(tenant, dashboard, n)
            _warm_per_tile(client, tenant, dashboard, tiles)
            read = _read_batched if use_batched else _read_per_tile
            # One unmeasured read first, so per-process caches are warm in both arms.
            read(client, tenant, dashboard, tiles)
            computes_before = sum(backend.calls.values())
            with CaptureQueriesContext(connection) as queries:
                start = time.perf_counter()
                read(client, tenant, dashboard, tiles)
                elapsed_ms = (time.perf_counter() - start) * 1000
            if sum(backend.calls.values()) != computes_before:
                raise RuntimeError("a cached read computed")
            out[f"pg_queries_{n}"] = len(queries.captured_queries)
            out[f"wall_ms_{n}"] = round(elapsed_ms, 1)
    return out


def scenario_c(cfg: Config, enabled: bool, run: int) -> dict[str, float]:
    """Viewers refreshing one logs tile: how often does it reach ClickHouse?"""
    tenant = make_tenant(f"C-{run}")
    viewers = [tenant.user] + [
        User.objects.create_and_join(tenant.organization, f"dv2-bench-{tenant.team.id}-{i}@example.com", None)
        for i in range(1, cfg.logs_viewers)
    ]
    backend = MockBackend(capacity=cfg.backend_capacity, seed=cfg.seed + run)
    config = {"limit": 10, "dateRange": {"date_from": "-1h"}}
    step_s = cfg.logs_window_s / cfg.logs_refreshes
    events = sorted(
        (refresh * step_s + viewer * step_s / cfg.logs_viewers, viewer)
        for refresh in range(cfg.logs_refreshes)
        for viewer in range(cfg.logs_viewers)
    )
    start = datetime(2026, 1, 1, 12, 0, tzinfo=UTC) + timedelta(days=run)
    with dashboard_v2(enabled), mocked_compute(tenant.team, backend), time_machine.travel(start, tick=False) as clock:
        for at, viewer in events:
            clock.move_to(start + timedelta(seconds=at))
            logs_list.run_logs_list_widget(tenant.team, config, user=viewers[viewer])
    return {"logs_computes": backend.calls["logs"], "logs_requests": len(events)}


def scenario_d(cfg: Config, enabled: bool, run: int) -> dict[str, float]:
    """A team with stale tiles of which a few were read in the last day: what does hourly warming compute?"""
    tenant = make_tenant(f"D-{run}")
    tenant.team.extra_settings = {"insights_cache_warming": True}
    tenant.team.save(update_fields=["extra_settings"])
    now = datetime.now(UTC)
    dashboard = Dashboard.objects.create(team=tenant.team, name="warming", last_accessed_at=now)
    tiles = _insight_tiles(tenant, dashboard, cfg.warming_stale_tiles)
    for tile in tiles:
        update_target_age(
            team_id=tenant.team.pk,
            insight_id=tile.insight_id,
            dashboard_id=dashboard.pk,
            target_age=now - timedelta(minutes=1),
        )
    for tile in tiles[: cfg.warming_read_tiles]:
        record_read(
            team_id=tenant.team.pk, insight_id=tile.insight_id, dashboard_id=dashboard.pk, at=now - timedelta(hours=2)
        )
    backend = MockBackend(capacity=cfg.backend_capacity, seed=cfg.seed + run)
    with (
        dashboard_v2(enabled),
        mocked_compute(tenant.team, backend),
        patch("posthog.caching.utils.sync_execute", return_value=[]),
        patch.object(warming.warm_insight_cache_task, "si") as schedule,
        patch.object(warming, "chain"),
    ):
        warming.schedule_warming_for_teams_task()
        ours = {tile.insight_id for tile in tiles}
        scheduled = [call.args for call in schedule.call_args_list if call.args[0] in ours]
        for insight_id, dashboard_id in scheduled:
            warming.warm_insight_cache_task(insight_id, dashboard_id)
    return {"tiles_warmed": len(scheduled), "warming_computes": backend.calls["analytics"]}


def scenario_e(cfg: Config, enabled: bool, run: int) -> dict[str, float]:
    """First load of a large board through the modelled client queue."""
    tenant = make_tenant(f"E-{run}")
    board = Dashboard.objects.create(team=tenant.team, name="large board")
    backend = MockBackend(capacity=cfg.backend_capacity, seed=cfg.seed + run)
    server = RunnerServer(tenant, cfg.server_workers)
    visible_only = enabled and STEPS["visible_tiles"].merged()
    requested = min(VISIBLE_TILES, cfg.large_board_tiles) if visible_only else cfg.large_board_tiles
    with dashboard_v2(enabled), mocked_compute(tenant.team, backend), live_limiters(tenant.organization):
        load = run_board_load(
            server.tile_request("metrics", board.id), requested, on_worker_exit=_close_thread_connections
        )
    if server.errors:
        raise RuntimeError(f"scenario E tile requests failed unexpectedly: {dict(server.errors)}")
    if load["outcomes"] != {"ok": requested}:
        raise RuntimeError(f"scenario E did not load every requested tile: {load['outcomes']}")
    return {
        "tile_queries": backend.calls["metrics"],
        "first_screen_ms": load["first_screen_ms"] or 0.0,
        "settled_ms": load["settled_ms"],
    }


# ---- assembly -----------------------------------------------------------------------------------


def _tiles(n: int) -> str:
    return f"{n} cached tile" if n == 1 else f"{n} cached tiles"


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    title: Callable[[Config], str]
    step_key: str
    modelled_client: bool
    run: Callable[[Config, bool, int], dict[str, float]]
    metrics: Callable[[Config], list[tuple[str, str, str, str]]]  # (result key, name, unit, better)


SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        id="A",
        title=lambda cfg: (
            f"Metrics board ({cfg.metrics_tiles} tiles, {cfg.refresh_interval_s:g} s refresh, {cfg.refresh_duration_s:g} s) "
            f"next to a {cfg.analytics_tiles}-tile analytics board"
        ),
        step_key="metrics_lane",
        modelled_client=False,
        run=scenario_a,
        metrics=lambda cfg: [
            ("metrics_rejected", "Rejected metrics tile queries", "count", "lower"),
            ("analytics_rejected", "Rejected analytics tile queries", "count", "lower"),
            # Served tiles only, measured from when the client queued the tile. A rejected tile never loads.
            ("metrics_p95_ms", "p95 metrics tile latency, served tiles", "ms", "lower"),
            ("analytics_p95_ms", "p95 analytics tile latency, served tiles", "ms", "lower"),
            ("analytics_slowdown_ms", "Analytics p95 minus analytics board alone", "ms", "lower"),
            ("tiles_served", "Tile queries served", "count", "higher"),
        ],
    ),
    ScenarioSpec(
        id="B",
        title=lambda cfg: "Cached board read",
        step_key="batched_read",
        modelled_client=False,
        run=scenario_b,
        metrics=lambda cfg: [
            m
            for n in cfg.cached_tile_counts
            for m in (
                (f"pg_queries_{n}", f"Postgres queries, {_tiles(n)}", "count", "lower"),
                (f"wall_ms_{n}", f"Server time, {_tiles(n)}", "ms", "lower"),
            )
        ],
    ),
    ScenarioSpec(
        id="C",
        title=lambda cfg: (
            f"Logs tile, {cfg.logs_viewers} viewers refreshing {cfg.logs_refreshes} times over {cfg.logs_window_s} s"
        ),
        step_key="logs_cache",
        modelled_client=False,
        run=scenario_c,
        metrics=lambda cfg: [("logs_computes", "ClickHouse logs computes", "count", "lower")],
    ),
    ScenarioSpec(
        id="D",
        title=lambda cfg: (
            f"Hourly warming, {cfg.warming_stale_tiles} stale tiles, {cfg.warming_read_tiles} read in the last 24 h"
        ),
        step_key="read_tiles_warming",
        modelled_client=False,
        run=scenario_d,
        metrics=lambda cfg: [
            ("tiles_warmed", "Tiles scheduled for warming", "count", "lower"),
            ("warming_computes", "ClickHouse computes from warming", "count", "lower"),
        ],
    ),
    ScenarioSpec(
        id="E",
        title=lambda cfg: (
            f"Large board first load ({cfg.large_board_tiles} tiles, {VISIBLE_TILES} visible), modelled client"
        ),
        step_key="visible_tiles",
        modelled_client=True,
        run=scenario_e,
        metrics=lambda cfg: [
            ("tile_queries", "Tile queries issued", "count", "lower"),
            ("first_screen_ms", "First 12 tiles loaded", "ms", "lower"),
            ("settled_ms", "All requested tiles loaded", "ms", "lower"),
        ],
    ),
]


def run_scorecard(cfg: Config, log: Callable[[str], None] = print) -> dict[str, Any]:
    started = time.monotonic()
    results: list[ScenarioResult] = []
    for spec in SCENARIOS:
        if spec.id not in cfg.scenarios:
            continue
        step = STEPS[spec.step_key]
        merged = step.merged()
        metric_specs = spec.metrics(cfg)
        metrics = {key: Metric(name=name, unit=unit, better=better) for key, name, unit, better in metric_specs}
        result = ScenarioResult(
            id=spec.id,
            title=spec.title(cfg),
            roadmap_step=step.roadmap_step,
            step_key=step.key,
            modelled_client=spec.modelled_client,
            metrics=list(metrics.values()),
        )
        for arm in cfg.arms:
            enabled = arm == "on"
            if enabled and not merged and not cfg.measure_unmerged:
                result.after_status = f"{NOT_MERGED} ({step.pr})"
                continue
            if enabled and not merged:
                result.after_status = f"measured, {NOT_MERGED} ({step.pr})"
            for run in range(cfg.repeats):
                log(f"[dv2-bench] scenario {spec.id} dashboard-v2={arm} run {run + 1}/{cfg.repeats}")
                values = spec.run(cfg, enabled, run)
                for key, metric in metrics.items():
                    (metric.after_runs if enabled else metric.before_runs).append(float(values[key]))
        if "on" not in cfg.arms:
            result.after_status = "not run"
        results.append(result)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": _git("rev-parse", "--short=12", "HEAD"),
        "master_base": _git("merge-base", "HEAD", "origin/master"),
        "mode": "quick" if cfg.quick else "full",
        "config": asdict(cfg),
        "runtime_s": round(time.monotonic() - started, 1),
        "steps": {
            key: {"roadmap_step": s.roadmap_step, "pr": s.pr, "title": s.title, "merged": s.merged()}
            for key, s in STEPS.items()
        },
        "scenarios": [_scenario_json(r) for r in results],
    }


def _git(*args: str) -> Optional[str]:
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=True,
            cwd=settings.BASE_DIR,
        ).stdout.strip()
    except Exception:
        return None


def _summary(runs: list[float]) -> Optional[float]:
    return round(statistics.median(runs), 1) if runs else None


def _change(before: Optional[float], after: Optional[float]) -> Optional[str]:
    if before is None or after is None:
        return None
    if before == after:
        return "0%"
    if before == 0:
        return f"{after - before:+g}"
    return f"{(after - before) / abs(before) * 100:+.0f}%"


def _scenario_json(result: ScenarioResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "title": result.title,
        "roadmap_step": result.roadmap_step,
        "step": result.step_key,
        "pr": STEPS[result.step_key].pr,
        "modelled_client": result.modelled_client,
        "after_status": result.after_status,
        "metrics": [
            {
                "name": m.name,
                "unit": m.unit,
                "better": m.better,
                "before": _summary(m.before_runs),
                "after": _summary(m.after_runs),
                "change": _change(_summary(m.before_runs), _summary(m.after_runs)),
                "before_runs": m.before_runs,
                "after_runs": m.after_runs,
            }
            for m in result.metrics
        ],
    }


def _fmt(value: Optional[float], unit: str) -> str:
    if value is None:
        return "-"
    text = f"{value:g}" if unit == "count" else f"{value:,.0f}"
    return f"{text} ms" if unit == "ms" else text


def _range(runs: list[float], unit: str) -> Optional[str]:
    if len(runs) < 2:
        return None
    low, high = min(runs), max(runs)
    if low == high:
        return "none"
    return f"{_fmt(low, unit)} to {_fmt(high, unit)}"


def _noise(metric: dict[str, Any]) -> str:
    ranges = [
        f"{arm} {r}"
        for arm, runs in (("before", metric["before_runs"]), ("after", metric["after_runs"]))
        if (r := _range(runs, metric["unit"])) is not None
    ]
    return "; ".join(ranges) if ranges else "single run"


def render_markdown(scorecard: dict[str, Any]) -> str:
    cfg = scorecard["config"]
    lines = [
        f"Dashboards v2 scorecard, {scorecard['mode']} mode, commit {scorecard['git_sha']} "
        f"(master base {(scorecard.get('master_base') or '?')[:12]}), "
        f"seed {cfg['seed']}, {cfg['repeats']} run(s) per arm, {scorecard['runtime_s']:.0f} s.",
        "Before = `dashboard-v2` off (today). After = `dashboard-v2` on. Values are medians across runs. "
        "Run-to-run range is the lowest and highest run of each arm.",
        "",
        "| Scenario | Step | Metric | Before | After | Change | Run-to-run range |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in scorecard["scenarios"]:
        label = f"{s['id']}. {s['title']}"
        measured = s["after_status"] == "measured" or s["after_status"].startswith("measured,")
        for m in s["metrics"]:
            after = _fmt(m["after"], m["unit"]) if measured else s["after_status"]
            change = (m["change"] or "-") if measured else "-"
            lines.append(
                f"| {label} | {s['roadmap_step']} ({s['pr']}) | {m['name']} | {_fmt(m['before'], m['unit'])} "
                f"| {after} | {change} | {_noise(m)} |"
            )
            label = ""
    lines.append("")
    lines.append(
        "Steps on this commit: "
        + ", ".join(
            f"{v['roadmap_step']} {v['pr']} {'merged' if v['merged'] else NOT_MERGED}"
            for v in scorecard["steps"].values()
        )
        + "."
    )
    return "\n".join(lines) + "\n"


def write_outputs(scorecard: dict[str, Any], out: Optional[str], md_out: Optional[str]) -> str:
    markdown = render_markdown(scorecard)
    if out:
        Path(out).write_text(json.dumps(scorecard, indent=2, sort_keys=False) + "\n")
    if md_out:
        Path(md_out).write_text(markdown)
    return markdown


def config_from_env() -> Config:
    raw = os.environ.get("DASHBOARD_V2_BENCH_CONFIG")
    if not raw:
        return Config.quick_mode()
    values = json.loads(raw)
    quick = values.pop("quick", False)
    for key in ("arms", "scenarios", "cached_tile_counts"):
        if key in values:
            values[key] = tuple(values[key])
    return Config.quick_mode(**values) if quick else Config(**values)
