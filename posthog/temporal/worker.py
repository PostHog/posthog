from temporalio.client import Client, TLSConfig
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.workflows import ACTIVITIES, WORKFLOWS


async def start_worker(host, port, namespace, task_queue, server_root_ca_cert=None, client_cert=None, client_key=None):
    tls = False
    if server_root_ca_cert and client_cert and client_key:
        tls = TLSConfig(
            server_root_ca_cert=server_root_ca_cert,
            client_cert=client_cert,
            client_private_key=client_key,
        )
    client = await Client.connect(f"{host}:{port}", namespace=namespace, tls=tls)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=WORKFLOWS,
        activities=ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
    )
    await worker.run()
