from datetime import datetime

from django.conf import settings
from temporalio.client import Client

from posthog.temporal.workflows import NoOpWorkflow


async def execute_noop_workflow(host, port) -> str:
    client = await Client.connect(f"{host}:{port}")
    result = await client.execute_workflow(
        NoOpWorkflow.run, datetime.now().isoformat(), id="noop-workflow", task_queue=settings.TEMPORAL_TASK_QUEUE
    )
    return result
