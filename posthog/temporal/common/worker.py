import socket
import datetime as dt
import itertools
import collections.abc
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from prometheus_client import CollectorRegistry
from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.worker import ResourceBasedSlotConfig, UnsandboxedWorkflowRunner, Worker, WorkerTuner

from posthog.temporal.common.client import connect
from posthog.temporal.common.combined_metrics_server import CombinedMetricsServer
from posthog.temporal.common.liveness_tracker import LivenessInterceptor
from posthog.temporal.common.logger import get_write_only_logger
from posthog.temporal.common.posthog_client import PostHogClientInterceptor

from products.batch_exports.backend.temporal.metrics import BatchExportsMetricsInterceptor

logger = get_write_only_logger()


BATCH_EXPORTS_LATENCY_HISTOGRAM_METRICS = (
    "batch_exports_activity_execution_latency",
    "batch_exports_activity_interval_execution_latency",
    "batch_exports_workflow_interval_execution_latency",
)
BATCH_EXPORTS_LATENCY_HISTOGRAM_BUCKETS = [
    1_000.0,
    30_000.0,  # 30 seconds
    60_000.0,  # 1 minute
    300_000.0,  # 5 minutes
    900_000.0,  # 15 minutes
    1_800_000.0,  # 30 minutes
    3_600_000.0,  # 1 hour
    21_600_000.0,  # 6 hours
    43_200_000.0,  # 12 hours
    86_400_000.0,  # 24 hours
]


@dataclass
class ManagedWorker:
    """A Temporal worker bundled with its associated resources for unified lifecycle management."""

    worker: Worker
    metrics_server: CombinedMetricsServer | None = None

    async def run(self) -> None:
        if self.metrics_server:
            await self.metrics_server.start()
        await self.worker.run()

    def is_shutdown(self) -> bool:
        return self.worker.is_shutdown

    async def shutdown(self) -> None:
        await self.worker.shutdown()
        if self.metrics_server:
            await self.metrics_server.stop()


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
    enable_combined_metrics_server: bool = True,
) -> ManagedWorker:
    """Connect to Temporal server and return a ManagedWorker containing the Worker and metrics server.

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
        enable_combined_metrics_server: Whether to start the combined metrics server. Defaults to True.
            Set to False to disable the metrics server (useful when it causes GIL contention issues).
    """

    metrics_server: CombinedMetricsServer | None = None

    if enable_combined_metrics_server:
        # Use an internal port for Temporal SDK metrics, which the combined metrics server
        # will fetch from and merge with prometheus_client metrics on the main metrics port.
        temporal_metrics_port = get_free_port()
        temporal_metrics_bind_address = f"127.0.0.1:{temporal_metrics_port}"

        # Create a separate CollectorRegistry for the metrics server to avoid lock contention
        # with any other parts of the application that might use the global REGISTRY.
        # This ensures the metrics server thread cannot deadlock with other threads.
        metrics_server_registry = CollectorRegistry()

        metrics_server = CombinedMetricsServer(
            port=metrics_port,
            temporal_metrics_url=f"http://{temporal_metrics_bind_address}/metrics",
            registry=metrics_server_registry,
        )
    else:
        # Expose Temporal SDK metrics directly on the public metrics port.
        temporal_metrics_bind_address = f"0.0.0.0:{metrics_port}"

    runtime = Runtime(
        telemetry=TelemetryConfig(
            metric_prefix=metric_prefix,
            metrics=PrometheusConfig(
                bind_address=temporal_metrics_bind_address,
                durations_as_seconds=False,
                # Units are u64 milliseconds in sdk-core,
                # given that the `duration_as_seconds` is `False`.
                # But in Python we still need to pass floats due to type hints.
                histogram_bucket_overrides=dict(
                    zip(
                        BATCH_EXPORTS_LATENCY_HISTOGRAM_METRICS,
                        itertools.repeat(BATCH_EXPORTS_LATENCY_HISTOGRAM_BUCKETS),
                    )
                )
                | {"batch_exports_activity_attempt": [1.0, 5.0, 10.0, 100.0]},
            ),
        )
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
            interceptors=[LivenessInterceptor(), PostHogClientInterceptor(), BatchExportsMetricsInterceptor()],
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
            interceptors=[LivenessInterceptor(), PostHogClientInterceptor(), BatchExportsMetricsInterceptor()],
            activity_executor=ThreadPoolExecutor(max_workers=max_concurrent_activities or 50),
            max_concurrent_activities=max_concurrent_activities or 50,
            max_concurrent_workflow_tasks=max_concurrent_workflow_tasks or 50,
            # Worker will flush heartbeats every
            # min(heartbeat_timeout * 0.8, max_heartbeat_throttle_interval).
            max_heartbeat_throttle_interval=dt.timedelta(seconds=5),
        )

    return ManagedWorker(worker=worker, metrics_server=metrics_server)


def get_free_port() -> int:
    """Find an available port on localhost.

    Note: There's a small race window between this returning and binding.
    Acceptable for localhost internal ports where collisions are rare,
    and would fail fast with a port-in-use exception if it occurs.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
