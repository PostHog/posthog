#!/usr/bin/env python3
"""
Metrics HTTP server for Granian multi-process setup.

Serves Prometheus metrics on port 8001 (configurable via PROMETHEUS_METRICS_EXPORT_PORT).
Aggregates metrics from all Granian worker processes using prometheus_client multiprocess
mode, and appends Granian's native runtime metrics (worker spawns/respawns, blocking pool
utilization and queue depth, connections, GIL wait — available since Granian 2.7.0) so
everything is scraped from the one port the charts already target.
Exposes Granian-equivalent metrics to maintain dashboard compatibility with previous Gunicorn setup.
"""

import os
import time
import logging
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest, multiprocess

logger = logging.getLogger(__name__)

# Loopback fetch must bypass the egress proxy: urllib honors HTTP_PROXY env by
# default, which routes 127.0.0.1 through Smokescreen — and Smokescreen blocks
# loopback by design. Per-code-path opt-out, never NO_PROXY (see
# charts docs/claude/egress-proxy.md).
_LOOPBACK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def create_granian_metrics() -> None:
    """
    Create Granian-equivalent metrics to maintain compatibility with existing Grafana dashboards.

    These metrics mirror the Gunicorn metrics that were previously exposed, allowing existing
    dashboards and alerts to continue working with minimal changes.
    """
    # Read Granian configuration from environment (granian's own env var names)
    workers = int(os.environ.get("GRANIAN_WORKERS", 4))
    threads = int(os.environ.get("GRANIAN_RUNTIME_THREADS", 1))

    # Expose static configuration as gauges. With PROMETHEUS_MULTIPROC_DIR set,
    # gauge writes land in the shared mmap files that MultiProcessCollector
    # already exports — registering them on the scrape registry as well would
    # export duplicate families, so registry stays None. multiprocess_mode="max"
    # yields one pid-less sample (only this process sets them).
    max_worker_threads = Gauge(
        "granian_max_worker_threads",
        "Maximum number of threads per worker",
        registry=None,
        multiprocess_mode="max",
    )
    max_worker_threads.set(threads)

    total_workers = Gauge(
        "granian_workers_total",
        "Total number of Granian workers configured",
        registry=None,
        multiprocess_mode="max",
    )
    total_workers.set(workers)

    # Configured backpressure isn't part of Granian's native metrics, so export it
    # here when set — it's the WSGI concurrency ceiling dashboards should show.
    # (Live blocking-thread counts DO come from the native metrics as
    # granian_blocking_threads — don't shadow that family here.)
    backpressure = os.environ.get("GRANIAN_BACKPRESSURE")
    if backpressure is not None:
        gauge = Gauge(
            "granian_backpressure",
            "Maximum in-flight requests per worker",
            registry=None,
            multiprocess_mode="max",
        )
        gauge.set(int(backpressure))


_NATIVE_CACHE_TTL_SECONDS = 5.0
_native_cache: tuple[float, bytes] = (0.0, b"")
_native_lock = threading.Lock()


def fetch_native_metrics() -> bytes:
    """Fetch Granian's own Prometheus exporter output for merging.

    The native exporter (GRANIAN_METRICS_ENABLED) binds loopback-only, so its
    runtime metrics ride along on this scrape instead of needing a second
    scrape target. Best-effort: a scrape must not fail while granian boots.

    Cached for a short TTL with the fetch serialized behind a lock, so scrape
    volume can't multiply loopback fetches — a stalled exporter costs at most
    one 2s wait per TTL window, not one pinned thread per scrape.
    """
    global _native_cache
    if os.environ.get("GRANIAN_METRICS_ENABLED", "false") != "true":
        return b""
    port = os.environ.get("GRANIAN_METRICS_PORT", "9090")
    with _native_lock:
        fetched_at, cached = _native_cache
        now = time.monotonic()
        if now - fetched_at < _NATIVE_CACHE_TTL_SECONDS:
            return cached
        try:
            with _LOOPBACK_OPENER.open(f"http://127.0.0.1:{port}/metrics", timeout=2) as response:
                body = response.read()
        except OSError:
            body = b""
        _native_cache = (now, body)
        return body


def main():
    """Start HTTP server exposing app multiprocess metrics merged with Granian's native metrics."""
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)

    # Create Granian-specific metrics for dashboard compatibility (they reach
    # the scrape via the multiprocess mmap files, not this registry)
    create_granian_metrics()

    port = int(os.environ.get("PROMETHEUS_METRICS_EXPORT_PORT", 8001))

    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = generate_latest(registry) + fetch_native_metrics()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            # Per-scrape access logs are noise.
            pass

    logger.info(f"Starting Prometheus metrics server on port {port}")
    ThreadingHTTPServer(("0.0.0.0", port), MetricsHandler).serve_forever()


if __name__ == "__main__":
    main()
