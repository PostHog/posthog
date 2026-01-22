import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)


class HealthState:
    """Tracks the health state of the consumer service."""

    def __init__(self, timeout_seconds: float = 60.0):
        self._timeout_seconds = timeout_seconds
        self._last_heartbeat: Optional[float] = None
        self._lock = threading.Lock()

    def report_healthy(self) -> None:
        """Called from the consumer loop to report the service is healthy."""
        with self._lock:
            self._last_heartbeat = time.monotonic()

    def is_healthy(self) -> bool:
        """Returns True if the last heartbeat was within the timeout period."""
        with self._lock:
            if self._last_heartbeat is None:
                return False
            elapsed = time.monotonic() - self._last_heartbeat
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
        else:  # TODO: add _health endpoint with metrics that we can use in grafana
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

    def _handle_readiness(self) -> None:  # TODO: make sure we check all the dependencies are healthy
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")


def start_health_server(port: int, health_state: HealthState) -> threading.Thread:
    HealthCheckHandler.health_state = health_state

    server = HTTPServer(
        ("0.0.0.0", port), HealthCheckHandler
    )  # TODO: not sure here if we should bind to localhost or 127.0.0.1
    server.timeout = 1.0

    def serve_forever():
        logger.info("health_server_started", port=port)
        server.serve_forever()

    thread = threading.Thread(target=serve_forever, daemon=True)
    thread.start()

    return thread
