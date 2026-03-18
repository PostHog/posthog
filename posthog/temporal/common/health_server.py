from aiohttp import web

from posthog.temporal.common.liveness_tracker import LivenessTracker
from posthog.temporal.common.logger import get_write_only_logger

logger = get_write_only_logger(__name__)


class HealthCheckServer:
    """Async HTTP server for Kubernetes health checks.

    Exposes /healthz (liveness) and /readyz (readiness) endpoints that verify
    the Temporal worker is actively processing workflows and activities.
    """

    def __init__(self, port: int, liveness_tracker: LivenessTracker, max_idle_seconds: float = 300.0):
        """Initialize the health check server.

        Args:
            port: Port to listen on for health check requests.
            liveness_tracker: Tracker that monitors worker activity.
            max_idle_seconds: Maximum time without execution before considering worker unhealthy.
                Default is 300 seconds (5 minutes). Set this based on your expected workflow
                frequency - it should be longer than typical gaps between workflows.
        """

        self._port = port
        self._liveness_tracker = liveness_tracker
        self._max_idle_seconds = max_idle_seconds
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def _handle_liveness(self, request: web.Request) -> web.Response:
        """Liveness probe: Is the worker process alive and processing work?

        Returns 200 if the worker has executed a workflow or activity within
        max_idle_seconds, indicating the event loop and threads are functioning.
        Returns 503 if the worker appears stuck (no executions for too long).
        """

        try:
            is_healthy = self._liveness_tracker.is_healthy(self._max_idle_seconds)
            idle_time = self._liveness_tracker.get_idle_time()

            if is_healthy:
                return web.json_response(
                    {
                        "status": "healthy",
                        "idle_seconds": round(idle_time, 2),
                        "max_idle_seconds": self._max_idle_seconds,
                    },
                    status=200,
                )
            else:
                logger.warning(
                    "health_server.liveness_failed",
                    idle_seconds=idle_time,
                    max_idle_seconds=self._max_idle_seconds,
                )
                return web.json_response(
                    {
                        "status": "unhealthy",
                        "idle_seconds": round(idle_time, 2),
                        "max_idle_seconds": self._max_idle_seconds,
                        "message": f"No workflow/activity execution in {idle_time:.1f}s (max: {self._max_idle_seconds}s)",
                    },
                    status=503,
                )
        except Exception as e:
            logger.exception("health_server.liveness_error", error=str(e))
            return web.json_response({"status": "error", "message": str(e)}, status=500)

    async def _handle_readiness(self, request: web.Request) -> web.Response:
        """Readiness probe: Is the worker ready to accept traffic?

        Currently returns the same status as liveness. Could be extended to check
        additional conditions like Temporal server connectivity.
        """

        return await self._handle_liveness(request)

    async def start(self) -> None:
        if self._app is not None:
            raise RuntimeError("Server already started")

        self._app = web.Application()
        self._app.router.add_get("/healthz", self._handle_liveness)
        self._app.router.add_get("/readyz", self._handle_readiness)

        self._runner = web.AppRunner(self._app, access_log=None)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, "0.0.0.0", self._port)
        await self._site.start()

        logger.info(
            "health_server.started",
            port=self._port,
            max_idle_seconds=self._max_idle_seconds,
        )

    async def stop(self) -> None:
        if self._runner is None:
            return

        await self._runner.cleanup()
        self._runner = None
        self._site = None
        self._app = None
        logger.info("health_server.stopped")
