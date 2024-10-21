import dataclasses
import uuid

from asgiref.sync import sync_to_async
from temporalio import activity

# TODO: remove dependency

from posthog.warehouse.external_data_source.jobs import (
    create_external_data_job,
)
from posthog.warehouse.models import aget_schema_by_id
from posthog.warehouse.models.external_data_schema import (
    ExternalDataSchema,
)
from posthog.temporal.common.logger import bind_temporal_worker_logger


@dataclasses.dataclass
class CreateExternalDataJobModelActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID


@activity.defn
async def create_external_data_job_model_activity(inputs: CreateExternalDataJobModelActivityInputs) -> tuple[str, bool]:
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

    try:
        job = await sync_to_async(create_external_data_job)(
            team_id=inputs.team_id,
            external_data_source_id=inputs.source_id,
            external_data_schema_id=inputs.schema_id,
            workflow_id=activity.info().workflow_id,
            workflow_run_id=activity.info().workflow_run_id,
        )

        schema = await sync_to_async(ExternalDataSchema.objects.get)(team_id=inputs.team_id, id=inputs.schema_id)
        schema.status = ExternalDataSchema.Status.RUNNING
        await sync_to_async(schema.save)()

        logger.info(
            f"Created external data job for external data source {inputs.source_id}",
        )

        schema_model = await aget_schema_by_id(inputs.schema_id, inputs.team_id)
        if schema_model is None:
            raise ValueError(f"Schema with ID {inputs.schema_id} not found")

        return str(job.id), schema_model.is_incremental
    except Exception as e:
        logger.exception(
            f"External data job failed on create_external_data_job_model_activity for {str(inputs.source_id)} with error: {e}"
        )
        raise
