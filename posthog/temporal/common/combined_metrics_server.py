import sys
import threading
import urllib.request
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
)
from http.server import BaseHTTPRequestHandler, HTTPServer

from prometheus_client import CollectorRegistry, generate_latest

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.logger import get_write_only_logger

logger = get_write_only_logger(__name__)


def create_handler(temporal_metrics_url: str, registry: CollectorRegistry) -> type[BaseHTTPRequestHandler]:
    class CombinedMetricsHandler(BaseHTTPRequestHandler):
        """HTTP handler that serves combined Temporal SDK and prometheus_client metrics."""

        def do_GET(self) -> None:
            if self.path in ("/metrics", "/"):
                self._serve_combined_metrics()
            else:
                try:
                    self.send_response(404)
                    self.end_headers()
                except (BrokenPipeError, ConnectionResetError):
                    logger.debug("combined_metrics_server.client_disconnected_on_404")

        def _serve_combined_metrics(self) -> None:
            try:
                # Fetch Temporal SDK metrics from its Prometheus endpoint
                temporal_output = b""
                try:
                    # this url is controlled by us, so we don't have to worry about it being a file:// url
                    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                    with urllib.request.urlopen(temporal_metrics_url, timeout=5) as response:
                        temporal_output = response.read()
                except Exception as e:
                    logger.warning("combined_metrics_server.temporal_fetch_failed", error=str(e))

                # Get prometheus_client metrics with timeout to prevent registry lock deadlock
                try:
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(generate_latest, registry)
                        client_output = future.result(timeout=5.0)
                except FuturesTimeoutError:
                    logger.warning("combined_metrics_server.registry_timeout")
                    client_output = b"# Prometheus registry timeout\n"

                # Combine both outputs, ensuring proper newline separation.
                # Prometheus text format requires metrics to be separated by exactly one newline.
                # Strip any trailing newlines from Temporal output and add exactly one to prevent
                # malformed output or extra blank lines between metric blocks.
                if temporal_output:
                    temporal_output = temporal_output.rstrip(b"\n") + b"\n"

                output = temporal_output + client_output

                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(output)
                except (BrokenPipeError, ConnectionResetError):
                    # Client disconnected before we could send the response
                    logger.debug("combined_metrics_server.client_disconnected")
                    return

            except Exception as e:
                capture_exception(e)
                logger.exception("combined_metrics_server.error", error=str(e))
                try:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(f"Error: {e}".encode())
                except (BrokenPipeError, ConnectionResetError):
                    # Client disconnected, nothing we can do
                    logger.debug("combined_metrics_server.client_disconnected_during_error")

        def log_message(self, format: str, *args: object) -> None:
            logger.debug(
                "combined_metrics_server.request",
                message=format % args,
                client_address=self.client_address[0],
            )

        def handle_error(self, request, client_address) -> None:  # noqa: ARG002
            """Override to handle errors during request processing gracefully.

            This provides better observability by sending exceptions to error tracking
            and using structured logging instead of stderr. Connection errors
            are logged at debug level to reduce noise.
            """
            exc_type, exc_value, _ = sys.exc_info()
            if exc_type in (BrokenPipeError, ConnectionResetError):
                logger.debug(
                    "combined_metrics_server.connection_error",
                    client_address=client_address[0] if client_address else None,
                )
            else:
                logger.exception(
                    "combined_metrics_server.request_error",
                    client_address=client_address[0] if client_address else None,
                )

            if exc_value is not None:
                capture_exception(exc_value)

    return CombinedMetricsHandler


class CombinedMetricsServer:
    """Metrics server combining Temporal SDK and prometheus_client metrics.

    Fetches Temporal metrics from its Prometheus HTTP endpoint and combines them
    with prometheus_client metrics on a single endpoint. This preserves the exact
    metric format that Temporal uses (including counter types without _total suffix).
    """

    def __init__(
        self,
        port: int,
        temporal_metrics_url: str,
        registry: CollectorRegistry,
    ):
        self._port = port
        self._temporal_metrics_url = temporal_metrics_url
        self._handler = create_handler(self._temporal_metrics_url, registry)
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("Server already started")

        self._server = HTTPServer(("0.0.0.0", self._port), self._handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="combined-metrics-server",
        )
        self._thread.start()

        logger.info(
            "combined_metrics_server.started",
            port=self._port,
            temporal_metrics_port=self._temporal_metrics_url,
        )

    def stop(self) -> None:
        if self._server is None:
            return

        self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
        logger.info("combined_metrics_server.stopped")
