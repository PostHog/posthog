from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.client import connect
from posthog.temporal.workflows import ACTIVITIES, WORKFLOWS


async def start_worker(host, port, namespace, task_queue, server_root_ca_cert=None, client_cert=None, client_key=None):

    client = await connect(host, port, namespace, server_root_ca_cert, client_cert, client_key)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
    )
    await worker.run()
