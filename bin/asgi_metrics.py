#!/usr/bin/env python3
"""
Metrics HTTP server for multi-process ASGI server setups.

Serves Prometheus metrics on port 8001 (configurable via PROMETHEUS_METRICS_EXPORT_PORT).
Aggregates metrics from all worker processes using prometheus_client multiprocess mode.
Supports Granian and Gunicorn+Uvicorn configurations.
"""

import os
import time
import logging

from prometheus_client import CollectorRegistry, Gauge, multiprocess, start_http_server

logger = logging.getLogger(__name__)


def create_server_metrics(registry: CollectorRegistry) -> None:
    """
    Create server-specific metrics to maintain compatibility with existing Grafana dashboards.

    Detects which server is being used (Granian, Gunicorn+Uvicorn) based on environment variables
    and exposes appropriate metrics for dashboard compatibility.
    """
    # Detect which server is being used
    if "GRANIAN_WORKERS" in os.environ:
        # Granian configuration
        workers = int(os.environ.get("GRANIAN_WORKERS", 4))
        threads = int(os.environ.get("GRANIAN_THREADS", 1))

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

    elif "UVICORN_WORKERS" in os.environ:
        # Gunicorn+Uvicorn configuration
        workers = int(os.environ.get("UVICORN_WORKERS", 4))
        timeout = int(os.environ.get("GUNICORN_TIMEOUT", 30))

        total_workers = Gauge(
            "gunicorn_workers_total",
            "Total number of Gunicorn+Uvicorn workers configured",
            registry=registry,
        )
        total_workers.set(workers)

        worker_timeout = Gauge(
            "gunicorn_worker_timeout_seconds",
            "Gunicorn worker timeout in seconds",
            registry=registry,
        )
        worker_timeout.set(timeout)


def main():
    """Start HTTP server to expose Prometheus metrics from all workers."""
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)

    # Create server-specific metrics for dashboard compatibility
    create_server_metrics(registry)

    port = int(os.environ.get("PROMETHEUS_METRICS_EXPORT_PORT", 8001))

    logger.info(f"Starting Prometheus metrics server on port {port}")
    start_http_server(port=port, registry=registry)

    # Keep the server running
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
