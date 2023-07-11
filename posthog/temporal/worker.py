from datetime import timedelta
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.client import connect
from posthog.temporal.workflows import ACTIVITIES, WORKFLOWS

import signal
import sys


async def start_worker(host, port, namespace, task_queue, server_root_ca_cert=None, client_cert=None, client_key=None):
    client = await connect(host, port, namespace, server_root_ca_cert, client_cert, client_key)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
        graceful_shutdown_timeout=timedelta(minutes=5),
    )

    # catch the TERM signal, and stop the worker gracefully
    # https://docs.temporal.io/docs/python/worker/#graceful-shutdown
    async def signal_handler(sig, frame):
        await worker.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)

    await worker.run()
