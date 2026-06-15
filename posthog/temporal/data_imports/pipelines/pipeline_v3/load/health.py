import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

import structlog
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest, multiprocess

logger = structlog.get_logger(__name__)


class HealthState:
    """Tracks the health state of the consumer service."""

    def __init__(self, timeout_seconds: float = 60.0):
        self._timeout_seconds = timeout_seconds
        self._created_at: float = time.monotonic()
        self._last_heartbeat: Optional[float] = None
        self._lock = threading.Lock()

    def report_healthy(self) -> None:
        """Called from the consumer loop to report the service is healthy."""
        with self._lock:
            self._last_heartbeat = time.monotonic()

    def is_healthy(self) -> bool:
        """Returns True if the last heartbeat was within the timeout period.

        Before the first heartbeat, the service is considered healthy for up to
        the timeout duration after creation — a startup grace period that prevents
        k8s from killing the pod before the consumer loop begins.
        """
        with self._lock:
            reference = self._last_heartbeat if self._last_heartbeat is not None else self._created_at
            elapsed = time.monotonic() - reference
            return elapsed < self._timeout_seconds


class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP handler for health check endpoints."""

    health_state: Optional[HealthState] = None

    def log_message(self, format: str, *args) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/_liveness":
            self._handle_liveness()
        elif self.path == "/_readiness":
            self._handle_readiness()
        elif self.path == "/_metrics":
            self._handle_metrics()
        else:
            self.send_error(404)

    def _handle_liveness(self) -> None:
        if self.health_state is not None and self.health_state.is_healthy():
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(503)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Service unhealthy")

    def _handle_readiness(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def _handle_metrics(self) -> None:
        # When multiple consumer processes share a pod, each writes its metrics
        # to PROMETHEUS_MULTIPROC_DIR; MultiProcessCollector aggregates them so
        # a single scrape endpoint reflects the whole pod.
        if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
            registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(registry)
            output = generate_latest(registry)
        else:
            output = generate_latest()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPE_LATEST)
        self.end_headers()
        self.wfile.write(output)


def start_health_server(port: int, health_state: HealthState) -> threading.Thread:
    HealthCheckHandler.health_state = health_state

    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.timeout = 1.0

    def serve_forever():
        logger.info("health_server_started", port=port)
        server.serve_forever()

    thread = threading.Thread(target=serve_forever, daemon=True)
    thread.start()

    return thread
