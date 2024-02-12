import signal
import sys
from datetime import timedelta

from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

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
):
    runtime = Runtime(telemetry=TelemetryConfig(metrics=PrometheusConfig(bind_address="0.0.0.0:%d" % metrics_port)))
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
        graceful_shutdown_timeout=timedelta(minutes=5),
        interceptors=[SentryInterceptor()],
    )

    # catch the TERM signal, and stop the worker gracefully
    # https://github.com/temporalio/sdk-python#worker-shutdown
    async def signal_handler(sig, frame):
        await worker.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)

    await worker.run()
