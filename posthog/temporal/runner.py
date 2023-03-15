from datetime import datetime

from temporalio.client import Client

from posthog.temporal.workflows import NoOpWorkflow


async def execute_noop_workflow(host, port):
    client = await Client.connect(f"{host}:{port}")
    result = await client.execute_workflow(NoOpWorkflow.run, datetime.now().isoformat())
    return result
