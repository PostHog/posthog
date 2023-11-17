from asgiref.sync import async_to_sync
from posthog import settings
from temporalio.client import Client
import dataclasses


@dataclasses.dataclass
class ExternalDataJobInputs:
    team_id: int
    external_data_source_id: str


@async_to_sync
async def start_external_data_job_workflow(temporal: Client, inputs: ExternalDataJobInputs) -> str:
    # TODO: add time to id
    workflow_id = f"{inputs.external_data_source_id}-external-data-job"
    await temporal.start_workflow(
        "external-data-job",
        inputs,
        id=workflow_id,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
    )

    return workflow_id
