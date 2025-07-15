import collections.abc
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import structlog
from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.client import connect
from posthog.temporal.common.posthog_client import PostHogClientInterceptor

logger = structlog.get_logger(__name__)


async def create_worker(
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
) -> Worker:
    """Connect to Temporal server and return a Worker.

    Arguments:
        host: The Temporal Server host.
        port: The Temporal Server port.
        metrics_port: Port used to serve Prometheus metrics.
        namespace: The Temporal namespace to connect to.
        task_queue: The task queue the worker will listen on.
        workflows: Workflows the worker is configured to run.
        activities: Activities the worker is configured to run.
        server_root_ca_cert: Root CA to validate the server certificate against.
        client_cert: Client certificate for TLS.
        client_key: Client private key for TLS.
        graceful_shutdown_timeout: Time to wait (in seconds) for graceful shutdown.
            By default we will wait 5 minutes. This should be always less than any
            timeouts used by deployment orchestrators.
        max_concurrent_workflow_tasks: Maximum number of concurrent workflow tasks
            the worker can handle. Defaults to 50.
        max_concurrent_activities: Maximum number of concurrent activity tasks the
            worker can handle. Defaults to 50.
    """

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
        interceptors=[PostHogClientInterceptor()],
        activity_executor=ThreadPoolExecutor(max_workers=max_concurrent_activities or 50),
        max_concurrent_activities=max_concurrent_activities or 50,
        max_concurrent_workflow_tasks=max_concurrent_workflow_tasks,
        # Worker will flush heartbeats every
        # min(heartbeat_timeout * 0.8, max_heartbeat_throttle_interval).
        max_heartbeat_throttle_interval=dt.timedelta(seconds=5),
    )
    return worker
