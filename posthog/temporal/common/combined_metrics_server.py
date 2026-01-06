import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from posthoganalytics import capture_exception
from prometheus_client import CollectorRegistry, generate_latest

from posthog.temporal.common.logger import get_write_only_logger

logger = get_write_only_logger(__name__)


def create_handler(temporal_metrics_url: str, registry: CollectorRegistry) -> type[BaseHTTPRequestHandler]:
    class CombinedMetricsHandler(BaseHTTPRequestHandler):
        """HTTP handler that serves combined Temporal SDK and prometheus_client metrics."""

        def do_GET(self) -> None:
            if self.path in ("/metrics", "/"):
                self._serve_combined_metrics()
            else:
                self.send_response(404)
                self.end_headers()

        def _serve_combined_metrics(self) -> None:
            try:
                content_type = "text/plain; version=0.0.4; charset=utf-8"
                # Fetch Temporal SDK metrics from its Prometheus endpoint
                temporal_output = b""
                try:
                    with urllib.request.urlopen(temporal_metrics_url, timeout=5) as response:
                        temporal_output = response.read()
                        content_type = response.getheader("Content-Type", content_type)
                except urllib.error.URLError as e:
                    logger.warning("combined_metrics_server.temporal_fetch_failed", error=str(e))

                # Get prometheus_client metrics
                client_output = generate_latest(registry)

                # Combine both outputs, ensuring proper newline separation.
                # Prometheus text format requires metrics to be separated by exactly one newline.
                # Strip any trailing newlines from Temporal output and add exactly one to prevent
                # malformed output or extra blank lines between metric blocks.
                if temporal_output:
                    temporal_output = temporal_output.rstrip(b"\n") + b"\n"

                output = temporal_output + client_output

                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(output)

            except Exception as e:
                capture_exception(e)
                logger.exception("combined_metrics_server.error", error=str(e))
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error: {e}".encode())

        def log_message(self, format: str, *args: object) -> None:
            logger.debug(
                "combined_metrics_server.request",
                message=format % args,
                client_address=self.client_address[0],
            )

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
        self._server = None
        self._thread = None
        logger.info("combined_metrics_server.stopped")
