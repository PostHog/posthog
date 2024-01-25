import dataclasses
import datetime as dt
import json
import uuid

from asgiref.sync import sync_to_async
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

# TODO: remove dependency
from posthog.temporal.batch_exports.base import PostHogWorkflow

from posthog.warehouse.data_load.validate_schema import validate_schema_and_update_table
from posthog.temporal.data_imports.pipelines.schemas import PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING
from posthog.temporal.data_imports.pipelines.pipeline import DataImportPipeline, PipelineInputs
from posthog.warehouse.external_data_source.jobs import (
    create_external_data_job,
    get_external_data_job,
    update_external_job_status,
)
from posthog.warehouse.models import (
    ExternalDataJob,
    get_active_schemas_for_source_id,
    sync_old_schemas_with_new_schemas,
    ExternalDataSource,
)
from posthog.warehouse.models.external_data_schema import get_postgres_schemas
from posthog.temporal.common.logger import bind_temporal_worker_logger
from typing import Tuple
import asyncio


@dataclasses.dataclass
class CreateExternalDataJobInputs:
    team_id: int
    external_data_source_id: uuid.UUID


@activity.defn
async def create_external_data_job_model(inputs: CreateExternalDataJobInputs) -> Tuple[str, list[str]]:
    run = await sync_to_async(create_external_data_job)(  # type: ignore
        team_id=inputs.team_id,
        external_data_source_id=inputs.external_data_source_id,
        workflow_id=activity.info().workflow_id,
    )

    source = await sync_to_async(ExternalDataSource.objects.get)(  # type: ignore
        team_id=inputs.team_id, id=inputs.external_data_source_id
    )
    source.status = "Running"
    await sync_to_async(source.save)()  # type: ignore

    if source.source_type == ExternalDataSource.Type.POSTGRES:
        host = source.job_inputs.get("host")
        port = source.job_inputs.get("port")
        user = source.job_inputs.get("user")
        password = source.job_inputs.get("password")
        database = source.job_inputs.get("database")
        sslmode = source.job_inputs.get("sslmode")
        schema = source.job_inputs.get("schema")
        schemas_to_sync = await sync_to_async(get_postgres_schemas)(  # type: ignore
            host, port, database, user, password, sslmode, schema
        )
    else:
        schemas_to_sync = list(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[source.source_type])

    await sync_to_async(sync_old_schemas_with_new_schemas)(  # type: ignore
        schemas_to_sync,
        source_id=inputs.external_data_source_id,
        team_id=inputs.team_id,
    )

    schemas = await sync_to_async(get_active_schemas_for_source_id)(  # type: ignore
        team_id=inputs.team_id, source_id=inputs.external_data_source_id
    )

    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

    logger.info(
        f"Created external data job with for external data source {inputs.external_data_source_id}",
    )

    return str(run.id), schemas


@dataclasses.dataclass
class UpdateExternalDataJobStatusInputs:
    id: str
    team_id: int
    run_id: str
    status: str
    latest_error: str | None


@activity.defn
async def update_external_data_job_model(inputs: UpdateExternalDataJobStatusInputs) -> None:
    await sync_to_async(update_external_job_status)(  # type: ignore
        run_id=uuid.UUID(inputs.id),
        status=inputs.status,
        latest_error=inputs.latest_error,
        team_id=inputs.team_id,
    )

    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)
    logger.info(
        f"Updated external data job with for external data source {inputs.run_id} to status {inputs.status}",
    )


@dataclasses.dataclass
class ValidateSchemaInputs:
    run_id: str
    team_id: int
    schemas: list[str]


@activity.defn
async def validate_schema_activity(inputs: ValidateSchemaInputs) -> None:
    await sync_to_async(validate_schema_and_update_table)(  # type: ignore
        run_id=inputs.run_id,
        team_id=inputs.team_id,
        schemas=inputs.schemas,
    )

    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)
    logger.info(
        f"Validated schema for external data job {inputs.run_id}",
    )


@dataclasses.dataclass
class ExternalDataWorkflowInputs:
    team_id: int
    external_data_source_id: uuid.UUID


@dataclasses.dataclass
class ExternalDataJobInputs:
    team_id: int
    source_id: uuid.UUID
    run_id: str
    schemas: list[str]


@activity.defn
async def run_external_data_job(inputs: ExternalDataJobInputs) -> None:
    model: ExternalDataJob = await sync_to_async(get_external_data_job)(  # type: ignore
        team_id=inputs.team_id,
        run_id=inputs.run_id,
    )

    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

    job_inputs = PipelineInputs(
        source_id=inputs.source_id,
        schemas=inputs.schemas,
        run_id=inputs.run_id,
        team_id=inputs.team_id,
        job_type=model.pipeline.source_type,
        dataset_name=model.folder_path,
    )

    source = None
    if model.pipeline.source_type == ExternalDataSource.Type.STRIPE:
        from posthog.temporal.data_imports.pipelines.stripe.helpers import stripe_source

        stripe_secret_key = model.pipeline.job_inputs.get("stripe_secret_key", None)
        if not stripe_secret_key:
            raise ValueError(f"Stripe secret key not found for job {model.id}")
        source = stripe_source(
            api_key=stripe_secret_key, endpoints=tuple(inputs.schemas), job_id=str(model.id), team_id=inputs.team_id
        )
    elif model.pipeline.source_type == ExternalDataSource.Type.HUBSPOT:
        from posthog.temporal.data_imports.pipelines.hubspot.auth import refresh_access_token
        from posthog.temporal.data_imports.pipelines.hubspot import hubspot

        hubspot_access_code = model.pipeline.job_inputs.get("hubspot_secret_key", None)
        refresh_token = model.pipeline.job_inputs.get("hubspot_refresh_token", None)
        if not refresh_token:
            raise ValueError(f"Hubspot refresh token not found for job {model.id}")

        if not hubspot_access_code:
            hubspot_access_code = refresh_access_token(refresh_token)

        source = hubspot(
            api_key=hubspot_access_code,
            refresh_token=refresh_token,
            job_id=str(model.id),
            team_id=inputs.team_id,
            endpoints=tuple(inputs.schemas),
        )
    elif model.pipeline.source_type == ExternalDataSource.Type.POSTGRES:
        from posthog.temporal.data_imports.pipelines.postgres import postgres_source

        host = model.pipeline.job_inputs.get("host")
        port = model.pipeline.job_inputs.get("port")
        user = model.pipeline.job_inputs.get("user")
        password = model.pipeline.job_inputs.get("password")
        database = model.pipeline.job_inputs.get("database")
        sslmode = model.pipeline.job_inputs.get("sslmode")
        schema = model.pipeline.job_inputs.get("schema")

        source = postgres_source(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            sslmode=sslmode,
            schema=schema,
            table_names=inputs.schemas,
        )

    else:
        raise ValueError(f"Source type {model.pipeline.source_type} not supported")

    # Temp background heartbeat for now
    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(10)
            activity.heartbeat()

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        await DataImportPipeline(job_inputs, source, logger).run()
    finally:
        heartbeat_task.cancel()
        await asyncio.wait([heartbeat_task])


# TODO: update retry policies
@workflow.defn(name="external-data-job")
class ExternalDataJobWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExternalDataWorkflowInputs:
        loaded = json.loads(inputs[0])
        return ExternalDataWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: ExternalDataWorkflowInputs):
        logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

        # create external data job and trigger activity
        create_external_data_job_inputs = CreateExternalDataJobInputs(
            team_id=inputs.team_id,
            external_data_source_id=inputs.external_data_source_id,
        )

        run_id, schemas = await workflow.execute_activity(
            create_external_data_job_model,
            create_external_data_job_inputs,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

        update_inputs = UpdateExternalDataJobStatusInputs(
            id=run_id, run_id=run_id, status=ExternalDataJob.Status.COMPLETED, latest_error=None, team_id=inputs.team_id
        )

        try:
            job_inputs = ExternalDataJobInputs(
                source_id=inputs.external_data_source_id,
                team_id=inputs.team_id,
                run_id=run_id,
                schemas=schemas,
            )

            await workflow.execute_activity(
                run_external_data_job,
                job_inputs,
                start_to_close_timeout=dt.timedelta(hours=4),
                retry_policy=RetryPolicy(maximum_attempts=5),
                heartbeat_timeout=dt.timedelta(minutes=1),
            )

            # check schema first
            validate_inputs = ValidateSchemaInputs(run_id=run_id, team_id=inputs.team_id, schemas=schemas)

            await workflow.execute_activity(
                validate_schema_activity,
                validate_inputs,
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

        except exceptions.ActivityError as e:
            if isinstance(e.cause, exceptions.CancelledError):
                update_inputs.status = ExternalDataJob.Status.CANCELLED
            else:
                update_inputs.status = ExternalDataJob.Status.FAILED
            logger.error(
                f"External data job failed for external data source {inputs.external_data_source_id} with error: {e.cause}"
            )
            update_inputs.latest_error = str(e.cause)
            raise
        except Exception as e:
            logger.error(
                f"External data job failed for external data source {inputs.external_data_source_id} with error: {e}"
            )
            # Catch all
            update_inputs.latest_error = "An unexpected error has ocurred"
            update_inputs.status = ExternalDataJob.Status.FAILED
            raise
        finally:
            await workflow.execute_activity(
                update_external_data_job_model,
                update_inputs,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=0,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError", "DoesNotExist"],
                ),
            )
