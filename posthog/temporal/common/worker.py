import asyncio
import collections.abc
import datetime as dt
import signal
from concurrent.futures import ThreadPoolExecutor

import structlog
from django.conf import settings
from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.client import connect
from posthog.temporal.common.posthog_client import PostHogClientInterceptor
from posthog.temporal.common.sentry import SentryInterceptor

logger = structlog.get_logger(__name__)


def _debug_pyarrows():
    if settings.PYARROW_DEBUG_LOGGING:
        import pyarrow as pa

        pa.log_memory_allocations(enable=True)


async def start_worker(
    host: str,
    port: int,
    metrics_port: int,
    namespace: str,
    task_queue: str,
    workflows: collections.abc.Sequence[type],
    activities,
    server_root_ca_cert: str | None = None,
    client_cert: str | None = None,
    client_key: str | None = None,
    graceful_shutdown_timeout: dt.timedelta | None = None,
    max_concurrent_workflow_tasks: int | None = None,
    max_concurrent_activities: int | None = None,
):
    _debug_pyarrows()

    runtime = Runtime(telemetry=TelemetryConfig(metrics=PrometheusConfig(bind_address=f"0.0.0.0:{metrics_port:d}")))
    client = await connect(
        host,
        port,
        namespace,
        server_root_ca_cert,
        client_cert,
        client_key,
        runtime=runtime,
    )

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=workflows,
        activities=activities,
        workflow_runner=UnsandboxedWorkflowRunner(),
        graceful_shutdown_timeout=graceful_shutdown_timeout or dt.timedelta(minutes=5),
        interceptors=[SentryInterceptor(), PostHogClientInterceptor()],
        activity_executor=ThreadPoolExecutor(max_workers=max_concurrent_activities or 50),
        max_concurrent_activities=max_concurrent_activities or 50,
        max_concurrent_workflow_tasks=max_concurrent_workflow_tasks,
        # Worker will flush heartbeats every
        # min(heartbeat_timeout * 0.8, max_heartbeat_throttle_interval).
        max_heartbeat_throttle_interval=dt.timedelta(seconds=5),
    )

    # catch the TERM and INT signals, and stop the worker gracefully
    # https://github.com/temporalio/sdk-python#worker-shutdown
    async def shutdown_worker(s: str):
        logger.info("%s received, initiating Temporal worker shutdown", s)
        await worker.shutdown()
        logger.info("Finished Temporal worker shutdown")

    loop = asyncio.get_event_loop()
    shutdown_tasks = set()
    loop.add_signal_handler(signal.SIGINT, lambda: shutdown_tasks.add(asyncio.create_task(shutdown_worker("SIGINT"))))
    loop.add_signal_handler(signal.SIGTERM, lambda: shutdown_tasks.add(asyncio.create_task(shutdown_worker("SIGTERM"))))

    await worker.run()
