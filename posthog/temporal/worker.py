from temporalio.client import Client
from temporalio.worker import Worker


async def start_worker(host, port):
    # Create client connected to server at the given address
    client = await Client.connect(f"{host}:{port}")

    # Run the worker
    worker = Worker(client, task_queue="my-task-queue", workflows=[], activities=[])
    await worker.run()
