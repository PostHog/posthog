import signal
import sys
from datetime import timedelta

from temporalio.runtime import Runtime, TelemetryConfig, PrometheusConfig
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.client import connect
from posthog.temporal.workflows import ACTIVITIES, WORKFLOWS


async def start_worker(
    host,
    port,
    namespace,
    task_queue,
    server_root_ca_cert=None,
    client_cert=None,
    client_key=None,
):
    runtime = Runtime(telemetry=TelemetryConfig(metrics=PrometheusConfig(bind_address="0.0.0.0:8596")))
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
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
        graceful_shutdown_timeout=timedelta(minutes=5),
    )

    # catch the TERM signal, and stop the worker gracefully
    # https://github.com/temporalio/sdk-python#worker-shutdown
    async def signal_handler(sig, frame):
        await worker.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)

    await worker.run()
