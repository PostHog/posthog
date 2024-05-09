import dataclasses
import uuid

from asgiref.sync import sync_to_async
from temporalio import activity

# TODO: remove dependency
from posthog.temporal.data_imports.pipelines.schemas import PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING

from posthog.warehouse.external_data_source.jobs import (
    create_external_data_job,
)
from posthog.warehouse.models import sync_old_schemas_with_new_schemas, ExternalDataSource, aget_schema_by_id
from posthog.warehouse.models.external_data_schema import ExternalDataSchema, get_postgres_schemas
from posthog.temporal.common.logger import bind_temporal_worker_logger


@dataclasses.dataclass
class CreateExternalDataJobModelActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID


@activity.defn
async def create_external_data_job_model_activity(inputs: CreateExternalDataJobModelActivityInputs) -> tuple[str, bool]:
    run = await sync_to_async(create_external_data_job)(
        team_id=inputs.team_id,
        external_data_source_id=inputs.source_id,
        external_data_schema_id=inputs.schema_id,
        workflow_id=activity.info().workflow_id,
    )

    schema = await sync_to_async(ExternalDataSchema.objects.get)(team_id=inputs.team_id, id=inputs.schema_id)
    schema.status = ExternalDataSchema.Status.RUNNING
    await sync_to_async(schema.save)()

    source = await sync_to_async(ExternalDataSource.objects.get)(team_id=inputs.team_id, id=inputs.source_id)

    if source.source_type == ExternalDataSource.Type.POSTGRES:
        host = source.job_inputs.get("host")
        port = source.job_inputs.get("port")
        user = source.job_inputs.get("user")
        password = source.job_inputs.get("password")
        database = source.job_inputs.get("database")
        schema = source.job_inputs.get("schema")
        schemas_to_sync = await sync_to_async(get_postgres_schemas)(host, port, database, user, password, schema)
    else:
        schemas_to_sync = list(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING.get(source.source_type, ()))

    # TODO: this could cause a race condition where each schema worker creates the missing schema

    await sync_to_async(sync_old_schemas_with_new_schemas)(
        schemas_to_sync,
        source_id=inputs.source_id,
        team_id=inputs.team_id,
    )

    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

    logger.info(
        f"Created external data job for external data source {inputs.source_id}",
    )

    schema_model = await aget_schema_by_id(inputs.schema_id, inputs.team_id)
    if schema_model is None:
        raise ValueError(f"Schema with ID {inputs.schema_id} not found")

    return str(run.id), schema_model.is_incremental
