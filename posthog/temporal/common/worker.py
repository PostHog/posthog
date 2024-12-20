import asyncio
import signal
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.constants import DATA_WAREHOUSE_TASK_QUEUE_V2
from posthog.temporal.common.client import connect
from posthog.temporal.common.sentry import SentryInterceptor


async def start_worker(
    host,
    port,
    metrics_port,
    namespace,
    task_queue,
    workflows,
    activities,
    server_root_ca_cert=None,
    client_cert=None,
    client_key=None,
    max_concurrent_workflow_tasks=None,
    max_concurrent_activities=None,
):
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
    if task_queue == DATA_WAREHOUSE_TASK_QUEUE_V2:
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=workflows,
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
            graceful_shutdown_timeout=timedelta(minutes=5),
            interceptors=[SentryInterceptor()],
            activity_executor=ThreadPoolExecutor(max_workers=max_concurrent_activities or 50),
            # Only run one workflow at a time
            max_concurrent_activities=1,
            max_concurrent_workflow_task_polls=1,
            max_concurrent_workflow_tasks=1,
            max_cached_workflows=0,
        )
    else:
        worker = Worker(
            client,
            task_queue=task_queue,
            workflows=workflows,
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
            graceful_shutdown_timeout=timedelta(minutes=5),
            interceptors=[SentryInterceptor()],
            activity_executor=ThreadPoolExecutor(max_workers=max_concurrent_activities or 50),
            max_concurrent_activities=max_concurrent_activities or 50,
            max_concurrent_workflow_tasks=max_concurrent_workflow_tasks,
        )

    # catch the TERM signal, and stop the worker gracefully
    # https://github.com/temporalio/sdk-python#worker-shutdown
    async def shutdown_worker():
        await worker.shutdown()

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(shutdown_worker()))

    await worker.run()
