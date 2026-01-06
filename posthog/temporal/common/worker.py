import datetime as dt
import collections.abc
from concurrent.futures import ThreadPoolExecutor

from temporalio.runtime import MetricBuffer, Runtime, TelemetryConfig
from temporalio.worker import ResourceBasedSlotConfig, UnsandboxedWorkflowRunner, Worker, WorkerTuner

from posthog.temporal.common.client import connect
from posthog.temporal.common.combined_metrics_server import start_combined_metrics_server
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.common.posthog_client import PostHogClientInterceptor

from products.batch_exports.backend.temporal.metrics import BatchExportsMetricsInterceptor

logger = get_write_only_logger()

# Buffer size for Temporal metrics - should be large enough to hold all metrics between scrapes
METRIC_BUFFER_SIZE = 10000


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
    metric_prefix: str | None = None,
    use_pydantic_converter: bool = False,
    target_memory_usage: float | None = None,
    target_cpu_usage: float | None = None,
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
        metric_prefix: Prefix to apply to metrics emitted by this worker, if
            left unset (`None`) Temporal will default to "temporal_".
        use_pydantic_converter: Flag to enable Pydantic data converter
        target_memory_usage: Fraction of available memory to use, between 0.0 and 1.0.
            If not set, worker will use max_concurrent_{activities, workflow_tasks} to dictate number of slots.
        target_cpu_usage: Fraction of available CPU to use, between 0.0 and 1.0.
            Defaults to 1.0. Only takes effect if target_memory_usage is set.
    """

    # Use MetricBuffer to collect Temporal SDK metrics directly (no HTTP needed).
    # The combined metrics server reads from this buffer and serves all metrics
    # (both Temporal and prometheus_client) on a single endpoint.
    metric_buffer = MetricBuffer(buffer_size=METRIC_BUFFER_SIZE)

    runtime = Runtime(
        telemetry=TelemetryConfig(
            metric_prefix=metric_prefix,
            metrics=metric_buffer,
        )
    )

    start_combined_metrics_server(
        port=metrics_port,
        metric_buffer=metric_buffer,
        metric_prefix=metric_prefix or "",
    )
    client = await connect(
        host,
        port,
        namespace,
        server_root_ca_cert,
        client_cert,
        client_key,
        runtime=runtime,
        use_pydantic_converter=use_pydantic_converter,
    )

    if target_memory_usage is not None:
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=workflows,
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
            graceful_shutdown_timeout=graceful_shutdown_timeout or dt.timedelta(minutes=5),
            interceptors=[PostHogClientInterceptor(), BatchExportsMetricsInterceptor()],
            activity_executor=ThreadPoolExecutor(max_workers=max_concurrent_activities or 50),
            tuner=WorkerTuner.create_resource_based(
                target_memory_usage=target_memory_usage,
                target_cpu_usage=target_cpu_usage or 1.0,
                workflow_config=ResourceBasedSlotConfig(maximum_slots=max_concurrent_workflow_tasks or 50),
                activity_config=ResourceBasedSlotConfig(maximum_slots=max_concurrent_activities or 50),
            ),
            # Worker will flush heartbeats every
            # min(heartbeat_timeout * 0.8, max_heartbeat_throttle_interval).
            max_heartbeat_throttle_interval=dt.timedelta(seconds=5),
        )
    else:
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=workflows,
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
            graceful_shutdown_timeout=graceful_shutdown_timeout or dt.timedelta(minutes=5),
            interceptors=[PostHogClientInterceptor(), BatchExportsMetricsInterceptor()],
            activity_executor=ThreadPoolExecutor(max_workers=max_concurrent_activities or 50),
            max_concurrent_activities=max_concurrent_activities or 50,
            max_concurrent_workflow_tasks=max_concurrent_workflow_tasks or 50,
            # Worker will flush heartbeats every
            # min(heartbeat_timeout * 0.8, max_heartbeat_throttle_interval).
            max_heartbeat_throttle_interval=dt.timedelta(seconds=5),
        )

    return worker
