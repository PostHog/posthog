import time
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from aiohttp import ClientSession, ClientTimeout
from prometheus_client import CollectorRegistry, Counter, Gauge

from posthog.temporal.common.combined_metrics_server import CombinedMetricsServer
from posthog.temporal.common.worker import get_free_port


def create_mock_temporal_server(port: int, metrics_content: bytes) -> HTTPServer:
    """Create a mock HTTP server that returns the given metrics content."""

    class MockHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(metrics_content)

        def log_message(self, format: str, *args: object) -> None:
            pass  # Suppress logging

    server = HTTPServer(("127.0.0.1", port), MockHandler)
    return server


def create_mock_temporal_server_with_error(port: int, status_code: int) -> HTTPServer:
    """Create a mock HTTP server that returns an HTTP error."""

    class ErrorHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(status_code)
            self.end_headers()
            self.wfile.write(b"# temporal metrics are not included")

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", port), ErrorHandler)
    return server


def create_mock_temporal_server_with_delay(port: int, delay_seconds: float) -> HTTPServer:
    """Create a mock HTTP server that delays before responding."""

    class SlowHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            time.sleep(delay_seconds)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"# HELP slow_metric A slow metric\n")

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", port), SlowHandler)
    return server


@pytest.fixture
def isolated_registry():
    """Create an isolated CollectorRegistry for test isolation."""
    return CollectorRegistry()


@pytest.fixture
def test_counter(isolated_registry):
    """Create a test prometheus_client counter in an isolated registry."""
    counter_name = "test_counter"
    counter = Counter(counter_name, "A test counter for combined metrics", registry=isolated_registry)
    counter.inc()
    return counter_name


@pytest.fixture
def test_gauge(isolated_registry):
    """Create a test prometheus_client gauge in an isolated registry.

    Uses Gauge instead of Counter to avoid _created metric for cleaner test comparisons.
    """
    gauge_name = "test_gauge"
    gauge = Gauge(gauge_name, "A test gauge", registry=isolated_registry)
    gauge.set(100)
    return gauge_name


class TestCombinedMetricsServer:
    @pytest.mark.asyncio
    async def test_serves_combined_metrics(self, test_counter, isolated_registry):
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        # Mock Temporal metrics
        temporal_metrics = b"""# HELP temporal_workflow_completed Workflow completions
# TYPE temporal_workflow_completed counter
temporal_workflow_completed{namespace="default"} 42
# HELP temporal_request Count of client request successes by rpc name
# TYPE temporal_request counter
temporal_request{operation="GetSystemInfo",service_name="temporal-core-sdk"} 1
temporal_request{namespace="default",operation="DescribeNamespace",service_name="temporal-core-sdk"} 1
# HELP temporal_long_request_latency Histogram of client long-poll request latencies
# TYPE temporal_long_request_latency histogram
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="50"} 8
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="100"} 8
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="500"} 8
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="1000"} 8
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="2500"} 8
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="10000"} 8
temporal_long_request_latency_bucket{namespace="default",operation="PollActivityTaskQueue",service_name="temporal-core-sdk",task_queue="development-task-queue",le="+Inf"} 313
"""

        mock_server = create_mock_temporal_server(temporal_port, temporal_metrics)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        await server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/metrics"
            async with ClientSession() as session:
                async with session.get(url) as response:
                    content = await response.text()

            # Check Temporal metrics are included
            assert temporal_metrics.decode() in content
            # Check prometheus_client metrics are included
            assert test_counter in content
        finally:
            await server.stop()
            mock_server.shutdown()

    @pytest.mark.asyncio
    async def test_serves_metrics_when_temporal_unavailable(self, test_counter, isolated_registry):
        temporal_port = get_free_port()  # No server running on this port
        metrics_port = get_free_port()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        await server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/metrics"
            async with ClientSession() as session:
                async with session.get(url) as response:
                    content = await response.text()

            # prometheus_client metrics should still be served
            assert test_counter in content
            assert "temporal" not in content
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_paths(self, isolated_registry):
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        await server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/unknown"
            async with ClientSession() as session:
                async with session.get(url) as response:
                    assert response.status == 404
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_root_path_serves_metrics(self, test_counter, isolated_registry):
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        temporal_metrics = b"""# HELP temporal_active_workers Active workers
# TYPE temporal_active_workers gauge
temporal_active_workers{task_queue="main"} 5
"""

        mock_server = create_mock_temporal_server(temporal_port, temporal_metrics)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        await server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/"
            async with ClientSession() as session:
                async with session.get(url) as response:
                    content = await response.text()

            assert temporal_metrics.decode() in content
            assert test_counter in content
        finally:
            await server.stop()
            mock_server.shutdown()

    @pytest.mark.asyncio
    async def test_counter_metrics_preserve_type_without_total_suffix(self, isolated_registry):
        """Verify that Temporal counter metrics preserve their format when passed through."""
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        # This is the format Temporal produces with counters_total_suffix=False
        # This is different compared to Pythons Prometheus Client which always adds the _total suffix.
        temporal_metrics = b"""# HELP temporal_request Count of requests
# TYPE temporal_request counter
temporal_request{operation="GetSystemInfo"} 1
temporal_request{operation="DescribeNamespace"} 2
"""

        mock_server = create_mock_temporal_server(temporal_port, temporal_metrics)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        await server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/metrics"
            async with ClientSession() as session:
                async with session.get(url) as response:
                    content = await response.text()

            # Verify counter type is preserved
            assert "# TYPE temporal_request counter" in content
            # Verify metric name has no _total suffix
            assert "temporal_request{" in content
            assert "temporal_request_total" not in content
        finally:
            await server.stop()
            mock_server.shutdown()

    @pytest.mark.asyncio
    async def test_adds_newline_when_temporal_output_missing_trailing_newline(self, test_gauge, isolated_registry):
        """Ensure proper newline separation when Temporal output doesn't end with newline."""
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        # Temporal output WITHOUT trailing newline (one should be added)
        temporal_metrics = b"# HELP temporal_metric A metric\n# TYPE temporal_metric gauge\ntemporal_metric 42"

        mock_server = create_mock_temporal_server(temporal_port, temporal_metrics)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        await server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/metrics"
            async with ClientSession() as session:
                async with session.get(url) as response:
                    content = await response.text()

            # Full expected output - newline added after temporal_metric 42
            expected = """# HELP temporal_metric A metric
# TYPE temporal_metric gauge
temporal_metric 42
# HELP test_gauge A test gauge
# TYPE test_gauge gauge
test_gauge 100.0
"""
            assert content == expected
        finally:
            await server.stop()
            mock_server.shutdown()

    @pytest.mark.asyncio
    async def test_no_extra_newlines_when_temporal_output_empty(self, test_counter, isolated_registry):
        """No extra newlines when Temporal returns empty response."""
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        # Empty Temporal output
        temporal_metrics = b""

        mock_server = create_mock_temporal_server(temporal_port, temporal_metrics)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        await server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/metrics"
            async with ClientSession() as session:
                async with session.get(url) as response:
                    content = await response.text()

            # prometheus_client metrics should be present
            assert test_counter in content
            # Output should not start with empty lines
            assert not content.startswith("\n")
        finally:
            await server.stop()
            mock_server.shutdown()

    @pytest.mark.asyncio
    async def test_duplicate_metric_names_both_present_in_output(self, isolated_registry):
        """Document: if both sources have same metric name, both appear in output.

        This is intentional - we pass through both outputs as-is and let Prometheus
        handle any duplicates. In practice, metric names should be unique across
        Temporal SDK metrics and application metrics.
        """
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        # Create a prometheus_client gauge with a name that could conflict
        # (using Gauge instead of Counter to avoid _total suffix for cleaner comparison)
        duplicate_name = "duplicate_metric"
        gauge = Gauge(duplicate_name, "App metric", registry=isolated_registry)
        gauge.set(100)

        # Temporal output with same metric name
        temporal_metrics = f"""# HELP {duplicate_name} Temporal metric
# TYPE {duplicate_name} counter
{duplicate_name} 42
""".encode()

        mock_server = create_mock_temporal_server(temporal_port, temporal_metrics)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        await server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/metrics"
            async with ClientSession() as session:
                async with session.get(url) as response:
                    content = await response.text()

            # Full diff comparison - Temporal metrics first, then prometheus_client
            # Note: Both sources may define the same metric name, resulting in duplicates
            expected = f"""# HELP {duplicate_name} Temporal metric
# TYPE {duplicate_name} counter
{duplicate_name} 42
# HELP {duplicate_name} App metric
# TYPE {duplicate_name} gauge
{duplicate_name} 100.0
"""
            assert content == expected
        finally:
            await server.stop()
            mock_server.shutdown()

    @pytest.mark.asyncio
    async def test_strips_multiple_trailing_newlines(self, test_gauge, isolated_registry):
        """Strip multiple trailing newlines to ensure exactly one newline separates outputs."""
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        # Temporal output with MULTIPLE trailing newlines (these should be stripped to exactly one)
        temporal_metrics = b"# HELP temporal_metric A metric\n# TYPE temporal_metric gauge\ntemporal_metric 42\n\n\n"

        mock_server = create_mock_temporal_server(temporal_port, temporal_metrics)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        await server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/metrics"
            async with ClientSession() as session:
                async with session.get(url) as response:
                    content = await response.text()

            # Full expected output - note exactly ONE newline between temporal and prometheus_client
            expected = """# HELP temporal_metric A metric
# TYPE temporal_metric gauge
temporal_metric 42
# HELP test_gauge A test gauge
# TYPE test_gauge gauge
test_gauge 100.0
"""
            assert content == expected
        finally:
            await server.stop()
            mock_server.shutdown()

    @pytest.mark.asyncio
    async def test_handles_temporal_http_error(self, test_counter, isolated_registry):
        """Gracefully degrade when Temporal returns HTTP error (e.g., 500)."""
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        mock_server = create_mock_temporal_server_with_error(temporal_port, 500)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        await server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/metrics"
            async with ClientSession() as session:
                async with session.get(url) as response:
                    content = await response.text()

            # prometheus_client metrics should still be served despite Temporal error
            assert test_counter in content
            # No Temporal metrics since it returned an error
            assert "temporal" not in content.lower() or "temporal_metrics" not in content
        finally:
            await server.stop()
            mock_server.shutdown()

    @pytest.mark.asyncio
    async def test_handles_temporal_timeout(self, test_counter, isolated_registry):
        """Gracefully degrade when Temporal is too slow to respond."""
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        # Create a server that delays longer than our 5s timeout
        mock_server = create_mock_temporal_server_with_delay(temporal_port, delay_seconds=7)
        mock_thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
        mock_thread.start()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        await server.start()

        try:
            url = f"http://127.0.0.1:{metrics_port}/metrics"
            # Use a longer timeout for the test request since we need to wait for the internal timeout
            async with ClientSession() as session:
                async with session.get(url, timeout=ClientTimeout(15)) as response:
                    content = await response.text()

            # prometheus_client metrics should still be served despite Temporal timeout
            assert test_counter in content
            # No Temporal metrics since it returned an error
            assert "temporal" not in content.lower()
        finally:
            await server.stop()
            mock_server.shutdown()

    @pytest.mark.asyncio
    async def test_start_twice_raises_error(self, isolated_registry):
        """Starting server twice should raise RuntimeError."""
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )
        await server.start()

        try:
            with pytest.raises(RuntimeError, match="Server already started"):
                await server.start()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_started_is_noop(self, isolated_registry):
        """Stopping server that wasn't started should be safe no-op."""
        temporal_port = get_free_port()
        metrics_port = get_free_port()

        server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://127.0.0.1:{temporal_port}/metrics",
            registry=isolated_registry,
        )

        # Should not raise any exception
        await server.stop()
        await server.stop()  # Multiple stops should also be safe


class TestGetFreePort:
    def test_returns_available_port(self):
        port = get_free_port()
        assert isinstance(port, int)
        assert port > 0

        # Verify the port is actually available
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
