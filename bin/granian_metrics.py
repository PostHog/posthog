#!/usr/bin/env python3
"""
Metrics HTTP server for Granian multi-process setup.

Serves Prometheus metrics on port 8001 (configurable via PROMETHEUS_METRICS_EXPORT_PORT).
Aggregates metrics from all Granian worker processes using prometheus_client multiprocess mode.
Exposes Granian-equivalent metrics to maintain dashboard compatibility with previous Gunicorn setup.
"""

import os
import time
import logging

from prometheus_client import CollectorRegistry, Gauge, multiprocess, start_http_server

logger = logging.getLogger(__name__)


def create_granian_metrics(registry: CollectorRegistry) -> None:
    """
    Create Granian-equivalent metrics to maintain compatibility with existing Grafana dashboards.

    These metrics mirror the Gunicorn metrics that were previously exposed, allowing existing
    dashboards and alerts to continue working with minimal changes.
    """
    # Read Granian configuration from environment
    workers = int(os.environ.get("GRANIAN_WORKERS", 4))
    threads = int(os.environ.get("GRANIAN_THREADS", 2))

    # Expose static configuration as gauges
    # These replace gunicorn_max_worker_connections and gunicorn_max_worker_threads
    max_worker_threads = Gauge(
        "granian_max_worker_threads",
        "Maximum number of threads per worker",
        registry=registry,
    )
    max_worker_threads.set(threads)

    total_workers = Gauge(
        "granian_workers_total",
        "Total number of Granian workers configured",
        registry=registry,
    )
    total_workers.set(workers)


def main():
    """Start HTTP server to expose Prometheus metrics from all workers."""
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)

    # Create Granian-specific metrics for dashboard compatibility
    create_granian_metrics(registry)

    port = int(os.environ.get("PROMETHEUS_METRICS_EXPORT_PORT", 8001))

    logger.info(f"Starting Prometheus metrics server on port {port}")
    start_http_server(port=port, registry=registry)

    # Keep the server running
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
