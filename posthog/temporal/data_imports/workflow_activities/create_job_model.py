import dataclasses
import uuid

from django.conf import settings
from django.db import close_old_connections
from temporalio import activity

# TODO: remove dependency

from posthog.constants import DATA_WAREHOUSE_TASK_QUEUE_V2
from posthog.warehouse.data_load.service import delete_external_data_schedule
from posthog.warehouse.models import ExternalDataJob, ExternalDataSource
from posthog.warehouse.models.external_data_schema import (
    ExternalDataSchema,
)
from posthog.temporal.common.logger import bind_temporal_worker_logger_sync


@dataclasses.dataclass
class CreateExternalDataJobModelActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID


def get_pipeline_version() -> str:
    if settings.TEMPORAL_TASK_QUEUE == DATA_WAREHOUSE_TASK_QUEUE_V2:
        return ExternalDataJob.PipelineVersion.V2

    return ExternalDataJob.PipelineVersion.V1


@activity.defn
def create_external_data_job_model_activity(
    inputs: CreateExternalDataJobModelActivityInputs,
) -> tuple[str, bool, str]:
    logger = bind_temporal_worker_logger_sync(team_id=inputs.team_id)

    close_old_connections()

    try:
        source_exists = ExternalDataSource.objects.filter(id=inputs.source_id).exclude(deleted=True).exists()
        schema_exists = ExternalDataSchema.objects.filter(id=inputs.schema_id).exclude(deleted=True).exists()

        if not source_exists or not schema_exists:
            delete_external_data_schedule(str(inputs.schema_id))
            raise Exception("Source or schema no longer exists - deleted temporal schedule")

        job = ExternalDataJob.objects.create(
            team_id=inputs.team_id,
            pipeline_id=inputs.source_id,
            schema_id=inputs.schema_id,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            workflow_id=activity.info().workflow_id,
            workflow_run_id=activity.info().workflow_run_id,
            pipeline_version=get_pipeline_version(),
        )

        schema = ExternalDataSchema.objects.get(team_id=inputs.team_id, id=inputs.schema_id)
        schema.status = ExternalDataSchema.Status.RUNNING
        schema.save()

        source: ExternalDataSource = schema.source

        logger.info(
            f"Created external data job for external data source {inputs.source_id}",
        )

        return str(job.id), schema.is_incremental, source.source_type
    except Exception as e:
        logger.exception(
            f"External data job failed on create_external_data_job_model_activity for {str(inputs.source_id)} with error: {e}"
        )
        raise
