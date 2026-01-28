import asyncio
from concurrent.futures import ThreadPoolExecutor

import aiohttp
from aiohttp import web
from prometheus_client import CollectorRegistry, generate_latest

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.logger import get_write_only_logger

logger = get_write_only_logger(__name__)


class CombinedMetricsServer:
    """Async metrics server combining Temporal SDK and prometheus_client metrics.

    Fetches Temporal metrics from its Prometheus HTTP endpoint and combines them
    with prometheus_client metrics on a single endpoint. This preserves the exact
    metric format that Temporal uses (including counter types without _total suffix).

    Uses aiohttp to avoid GIL contention with Temporal activities.
    """

    def __init__(
        self,
        port: int,
        temporal_metrics_url: str,
        registry: CollectorRegistry,
    ):
        self._port = port
        self._temporal_metrics_url = temporal_metrics_url
        self._registry = registry
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        # Dedicated single-threaded executor for generate_latest to avoid starving the default executor.
        # max_workers=1 ensures only one registry collection happens at a time (serialization).
        # If a collection deadlocks, the timeout will fire and shutdown(wait=False) prevents blocking.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="metrics-collector")

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        """Handle GET /metrics requests by combining Temporal SDK and prometheus_client metrics."""
        try:
            # Fetch Temporal SDK metrics from its Prometheus endpoint asynchronously
            temporal_output = b""
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(self._temporal_metrics_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            temporal_output = await resp.read()
                        else:
                            logger.warning(
                                "combined_metrics_server.temporal_fetch_failed",
                                status=resp.status,
                                error=f"HTTP {resp.status}",
                            )
            except Exception as e:
                logger.warning("combined_metrics_server.temporal_fetch_failed", error=str(e))

            # Get prometheus_client metrics in a dedicated thread pool to avoid blocking the event loop
            # or starving the default executor. Run with timeout to prevent registry lock issues.
            try:
                client_output = await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(self._executor, generate_latest, self._registry),
                    timeout=5.0,
                )
            except TimeoutError:
                logger.warning("combined_metrics_server.registry_timeout")
                client_output = b"# Prometheus registry timeout\n"

            # Combine both outputs, ensuring proper newline separation.
            # Prometheus text format requires metrics to be separated by exactly one newline.
            # Strip any trailing newlines from Temporal output and add exactly one to prevent
            # malformed output or extra blank lines between metric blocks.
            if temporal_output:
                temporal_output = temporal_output.rstrip(b"\n") + b"\n"

            output = temporal_output + client_output

            return web.Response(
                body=output,
                status=200,
                content_type="text/plain; version=0.0.4",
                charset="utf-8",
            )

        except Exception as e:
            capture_exception(e)
            logger.exception("combined_metrics_server.error", error=str(e))
            return web.Response(text=f"Error: {e}", status=500)

    async def start(self) -> None:
        if self._app is not None:
            raise RuntimeError("Server already started")

        self._app = web.Application()
        self._app.router.add_get("/metrics", self._handle_metrics)
        self._app.router.add_get("/", self._handle_metrics)

        self._runner = web.AppRunner(self._app, access_log=None)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, "0.0.0.0", self._port)
        await self._site.start()

        logger.info(
            "combined_metrics_server.started",
            port=self._port,
            temporal_metrics_url=self._temporal_metrics_url,
        )

    async def stop(self) -> None:
        if self._runner is None:
            return

        await self._runner.cleanup()
        self._runner = None
        self._site = None
        self._app = None

        # Shutdown the dedicated executor
        # wait=False is intentional: if generate_latest is stuck, don't block shutdown
        self._executor.shutdown(wait=False)

        logger.info("combined_metrics_server.stopped")
