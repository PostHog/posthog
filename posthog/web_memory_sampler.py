import os
import time
import logging
import threading

import structlog

logger = logging.getLogger(__name__)

_sampler_started = False
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


def _sample_loop(interval_seconds: float) -> None:
    log = structlog.get_logger("posthog.web_memory_sampler")
    pod = os.getenv("K8S_POD_NAME") or os.getenv("HOSTNAME")
    request_limit = os.getenv("NGINX_UNIT_REQUEST_LIMIT")
    while True:
        time.sleep(interval_seconds)
        rss_mb = current_rss_mb()
        if rss_mb is None:
            continue
        log.info(
            "worker_memory",
            pid=os.getpid(),
            rss_mb=round(rss_mb, 1),
            pod=pod,
            request_limit=request_limit,
        )


def start_web_memory_sampler() -> None:
    """Start a daemon thread that periodically logs this worker's RSS as
    `worker_memory`, so the gradual climb toward the cgroup limit that precedes
    an OOM kill is visible in PostHog logs rather than only on infra dashboards.

    Interval is set by WEB_MEMORY_SAMPLE_INTERVAL_SECONDS (default 30); set it to
    0 or less to disable. Best-effort and idempotent — never breaks startup."""
    global _sampler_started
    try:
        interval_seconds = float(os.getenv("WEB_MEMORY_SAMPLE_INTERVAL_SECONDS", "30"))
        if interval_seconds <= 0:
            return
        with _lock:
            if _sampler_started:
                return
            _sampler_started = True
        threading.Thread(
            target=_sample_loop,
            args=(interval_seconds,),
            name="web-memory-sampler",
            daemon=True,
        ).start()
    except Exception:
        logger.exception("failed to start web memory sampler")
