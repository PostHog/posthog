import os
import time
import logging
import threading

import structlog
from prometheus_client import Gauge

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_INTERVAL_SECONDS = 30.0

# Web-worker RSS, scraped via bin/unit_metrics.py's MultiProcessCollector. `livemax`
# reports the maximum across live workers as a single series, so the worker nearest the
# cgroup limit is visible without the per-pid cardinality — and stale-series-on-recycle,
# since a request-limited or OOM-killed worker never calls `mark_process_dead` — that
# `liveall` would accumulate. Per-worker detail lives in the `worker_memory` log line.
WORKER_RSS_MB = Gauge(
    "posthog_web_worker_rss_mb",
    "Maximum resident set size across live web worker processes, in MiB.",
    multiprocess_mode="livemax",
)

_sampler_started_pid: int | None = None
_lock = threading.Lock()


def current_rss_mb() -> float | None:
    """Resident set size of the current worker process in MiB, read from
    /proc/self/statm (field 2 = resident pages). Returns None when unavailable,
    e.g. on non-Linux dev machines where /proc is absent."""
    try:
        with open("/proc/self/statm") as statm:
            resident_pages = int(statm.read().split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return resident_pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)


def _sample_once(log: structlog.BoundLogger, pod: str | None, request_limit: str | None) -> None:
    rss_mb = current_rss_mb()
    if rss_mb is None:
        return
    rss_mb_rounded = round(rss_mb, 1)
    WORKER_RSS_MB.set(rss_mb_rounded)
    log.info(
        "worker_memory",
        rss_mb=rss_mb_rounded,
        pod=pod,
        request_limit=request_limit,
    )


def _sample_loop(interval_seconds: float) -> None:
    log = structlog.get_logger("posthog.web_memory_sampler")
    pod = os.getenv("K8S_POD_NAME") or os.getenv("HOSTNAME")
    request_limit = os.getenv("NGINX_UNIT_REQUEST_LIMIT")
    while True:
        time.sleep(interval_seconds)
        try:
            _sample_once(log, pod, request_limit)
        except Exception:
            logger.exception("web memory sample failed")


def start_web_memory_sampler() -> None:
    """Start a daemon thread that periodically records this worker's RSS — as the
    `posthog_web_worker_rss_mb` Prometheus gauge and a `worker_memory` log line — so the
    gradual climb toward the cgroup limit that precedes an OOM kill is visible in both
    metrics and PostHog logs rather than only on infra dashboards.

    MUST be called post-fork, from inside each worker (see posthog/wsgi.py). Nginx Unit
    forks workers from a prototype process that imported this module, and a thread started
    in the prototype does not survive the fork — an import-time start would only ever
    sample the idle prototype, never the workers that serve requests. The pid guard re-arms
    per process because the once-flag is copy-on-write-inherited from the prototype.

    Interval is set by WEB_MEMORY_SAMPLE_INTERVAL_SECONDS (default 30); set it to 0 or less
    to disable. Best-effort and idempotent — never breaks startup."""
    global _sampler_started_pid
    try:
        try:
            interval_seconds = float(
                os.getenv("WEB_MEMORY_SAMPLE_INTERVAL_SECONDS", str(DEFAULT_SAMPLE_INTERVAL_SECONDS))
            )
        except ValueError:
            interval_seconds = DEFAULT_SAMPLE_INTERVAL_SECONDS
        if interval_seconds <= 0:
            return
        interval_seconds = max(interval_seconds, 1.0)
        pid = os.getpid()
        with _lock:
            if _sampler_started_pid == pid:
                return
            _sampler_started_pid = pid
        threading.Thread(
            target=_sample_loop,
            args=(interval_seconds,),
            name="web-memory-sampler",
            daemon=True,
        ).start()
    except Exception:
        logger.exception("failed to start web memory sampler")
