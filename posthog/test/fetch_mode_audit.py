"""Audit lazy loads of related objects and deferred fields with Django fetch modes.

Set DJANGO_FETCH_MODE_AUDIT to pick a mode for the whole test session:

- ``peers``: the default fetch mode becomes FETCH_PEERS. A test whose query count drops has an N+1.
- ``log``: each lazy load is recorded with its call site, then loads one object like FETCH_ONE.

Both modes write per-test Postgres query counts, so a ``log`` run is the baseline for a ``peers`` run.
Results go to DJANGO_FETCH_MODE_AUDIT_DIR (default ``fetch-mode-audit``), one JSON file per process.
Run ``python -m posthog.test.fetch_mode_audit <log dir> [<peers dir>]`` to aggregate them.
"""

import os
import sys
import json
from collections import Counter, defaultdict
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_PREFIX = f"{REPO_ROOT}{os.sep}"
_THIS_FILE = str(Path(__file__).resolve())
_SKIPPED_PATH_PARTS = (f"{os.sep}site-packages{os.sep}", f"{os.sep}.venv{os.sep}", f"{os.sep}lib{os.sep}python")


def _is_test_path(path: str) -> bool:
    name = Path(path).name
    return (
        name.startswith("test_")
        or name == "conftest.py"
        or f"{os.sep}test{os.sep}" in path
        or f"{os.sep}tests{os.sep}" in path
    )


def _app_frames() -> tuple[str | None, str | None]:
    """Return the first repo frame, and the first repo frame outside test code."""
    first: str | None = None
    frame = sys._getframe(2)
    while frame is not None:
        path = frame.f_code.co_filename
        if path.startswith(_REPO_PREFIX) and path != _THIS_FILE and not any(p in path for p in _SKIPPED_PATH_PARTS):
            location = f"{path[len(_REPO_PREFIX) :]}:{frame.f_lineno} ({frame.f_code.co_name})"
            if first is None:
                first = location
            if not _is_test_path(path):
                return first, location
        frame = frame.f_back
    return first, None


@dataclass(frozen=False)
class _Site:
    count: int = 0
    multi_peer_count: int = 0
    max_peers: int = 0
    tests: Counter[str] = field(default_factory=Counter)


class _Recorder:
    def __init__(self) -> None:
        self.nodeid: str | None = None
        self.phase = "setup"
        self.sites: dict[tuple[str, str, str | None, str | None], _Site] = defaultdict(_Site)
        self.tests: dict[str, dict[str, int]] = defaultdict(Counter)

    def query(self) -> None:
        if self.nodeid is not None:
            self.tests[self.nodeid][f"{self.phase}_queries"] += 1

    def lazy_load(self, fetcher: Any, instance: Any) -> None:
        peers = sum(1 for ref in instance._state.peers if ref() is not None)
        target = f"{type(instance).__module__}.{type(instance).__qualname__}.{getattr(fetcher.field, 'name', '?')}"
        site, app_site = _app_frames()
        entry = self.sites[(target, type(fetcher).__name__, app_site, site)]
        entry.count += 1
        entry.max_peers = max(entry.max_peers, peers)
        if peers > 1:
            entry.multi_peer_count += 1
        if self.nodeid is not None:
            entry.tests[self.nodeid] += 1
            self.tests[self.nodeid][f"{self.phase}_lazy_loads"] += 1
            if peers > 1:
                self.tests[self.nodeid][f"{self.phase}_lazy_loads_with_peers"] += 1


RECORDER = _Recorder()


def _build_log_fetch_mode() -> Any:
    from django.db.models.fetch_modes import FetchMode  # noqa: PLC0415 — Django is set up after import

    class LogFetchOne(FetchMode):
        __slots__ = ()
        # Peers are tracked only to count them; the load itself is one object, like FETCH_ONE.
        track_peers = True

        def fetch(self, fetcher: Any, instance: Any) -> None:
            RECORDER.lazy_load(fetcher, instance)
            fetcher.fetch_one(instance)

        def __reduce__(self) -> str:
            return "FETCH_AUDIT_LOG"

    LogFetchOne.__module__ = __name__
    LogFetchOne.__qualname__ = "LogFetchOne"
    return LogFetchOne()


FETCH_AUDIT_LOG: Any = None


def install(mode: str) -> None:
    global FETCH_AUDIT_LOG

    from django.db.backends import utils as backend_utils  # noqa: PLC0415
    from django.db.models import (  # noqa: PLC0415
        FETCH_PEERS,
        query as query_module,
    )

    if mode == "peers":
        query_module.DEFAULT_FETCH_MODE = FETCH_PEERS
    elif mode == "log":
        FETCH_AUDIT_LOG = _build_log_fetch_mode()
        query_module.DEFAULT_FETCH_MODE = FETCH_AUDIT_LOG
    else:
        raise ValueError(f"DJANGO_FETCH_MODE_AUDIT must be 'peers' or 'log', not {mode!r}")

    original_execute = backend_utils.CursorWrapper.execute
    original_executemany = backend_utils.CursorWrapper.executemany

    def execute(self: Any, *args: Any, **kwargs: Any) -> Any:
        RECORDER.query()
        return original_execute(self, *args, **kwargs)

    def executemany(self: Any, *args: Any, **kwargs: Any) -> Any:
        RECORDER.query()
        return original_executemany(self, *args, **kwargs)

    backend_utils.CursorWrapper.execute = execute  # type: ignore[method-assign]
    backend_utils.CursorWrapper.executemany = executemany  # type: ignore[method-assign]


class FetchModeAuditPlugin:
    def __init__(self, mode: str, output_dir: Path) -> None:
        self._mode = mode
        self._output_dir = output_dir
        install(mode)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_setup(self, item: pytest.Item) -> Generator[None]:
        RECORDER.nodeid = item.nodeid
        RECORDER.phase = "setup"
        return (yield)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(self, item: pytest.Item) -> Generator[None]:
        RECORDER.phase = "call"
        return (yield)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_teardown(self, item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None]:
        RECORDER.phase = "teardown"
        try:
            return (yield)
        finally:
            RECORDER.nodeid = None

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "call":
            RECORDER.tests[report.nodeid]["failed"] = int(report.failed)

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
        shard = os.environ.get("DJANGO_FETCH_MODE_AUDIT_SHARD", "")
        out = self._output_dir / f"{self._mode}-{shard}-{worker}-{os.getpid()}.json"
        sites = [
            {
                "target": target,
                "fetcher": fetcher,
                "app_site": app_site,
                "first_site": site,
                "count": entry.count,
                "multi_peer_count": entry.multi_peer_count,
                "max_peers": entry.max_peers,
                "test_count": len(entry.tests),
                "top_tests": entry.tests.most_common(5),
            }
            for (target, fetcher, app_site, site), entry in RECORDER.sites.items()
        ]
        out.write_text(json.dumps({"mode": self._mode, "tests": RECORDER.tests, "sites": sites}))


def register(config: pytest.Config) -> None:
    mode = os.environ.get("DJANGO_FETCH_MODE_AUDIT")
    if not mode:
        return
    output_dir = Path(os.environ.get("DJANGO_FETCH_MODE_AUDIT_DIR", "fetch-mode-audit"))
    config.pluginmanager.register(FetchModeAuditPlugin(mode, output_dir), "posthog-fetch-mode-audit")


def _load(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(directory.rglob("*.json"))]


def _merge_tests(runs: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    # Several matrix legs run the same test; keep the largest count each leg reports.
    merged: dict[str, dict[str, int]] = defaultdict(dict)
    for run in runs:
        for nodeid, counts in run["tests"].items():
            for key, value in counts.items():
                merged[nodeid][key] = max(merged[nodeid].get(key, 0), value)
    return merged


def aggregate(log_dir: Path, peers_dir: Path | None, limit: int = 40) -> dict[str, Any]:
    log_runs = _load(log_dir)
    sites: dict[tuple[str, str | None], dict[str, Any]] = {}
    for run in log_runs:
        for s in run["sites"]:
            key = (s["target"], s["app_site"] or s["first_site"])
            agg = sites.setdefault(
                key,
                {
                    "target": s["target"],
                    "site": key[1],
                    "count": 0,
                    "multi_peer_count": 0,
                    "max_peers": 0,
                    "tests": Counter(),
                },
            )
            agg["count"] += s["count"]
            agg["multi_peer_count"] += s["multi_peer_count"]
            agg["max_peers"] = max(agg["max_peers"], s["max_peers"])
            agg["tests"].update(dict(s["top_tests"]))
    ranked_sites = sorted(sites.values(), key=lambda s: (s["multi_peer_count"], s["count"]), reverse=True)
    result: dict[str, Any] = {
        "sites": [{**s, "tests": s["tests"].most_common(3)} for s in ranked_sites[:limit]],
    }
    if peers_dir is not None:
        baseline = _merge_tests(log_runs)
        peers = _merge_tests(_load(peers_dir))
        drops = []
        for nodeid, before in baseline.items():
            after = peers.get(nodeid)
            if after is None:
                continue
            b = before.get("setup_queries", 0) + before.get("call_queries", 0)
            a = after.get("setup_queries", 0) + after.get("call_queries", 0)
            if a < b:
                drops.append(
                    {
                        "test": nodeid,
                        "before": b,
                        "after": a,
                        "saved": b - a,
                        "lazy_loads_with_peers": before.get("call_lazy_loads_with_peers", 0),
                        "failed_under_peers": after.get("failed", 0),
                    }
                )
        drops.sort(key=lambda d: d["saved"], reverse=True)
        result["query_drops"] = drops[:limit]
        result["query_drop_test_count"] = len(drops)
        result["failed_under_peers"] = sorted(n for n, c in peers.items() if c.get("failed"))
    return result


if __name__ == "__main__":
    print(  # noqa: T201
        json.dumps(
            aggregate(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None),
            indent=2,
        )
    )
