from datetime import timedelta

from temporalio.client import Client

from posthog.temporal.workflows import NoOpWorkflow


async def execute_noop_workflow(host, port):
    client = await Client.connect(f"{host}:{port}")
    result = await client.execute_workflow(
        NoOpWorkflow.run,
        start_to_close_timeout=timedelta(seconds=60),
        schedule_to_close_timeout=timedelta(minutes=5),
    )
    return result
