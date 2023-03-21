from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.workflows import ACTIVITIES, WORKFLOWS

TASK_QUEUE = "no-sendbox-python-django"


async def start_worker(host, port, task_queue):
    client = await Client.connect(f"{host}:{port}")
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
    )
    await worker.run()
