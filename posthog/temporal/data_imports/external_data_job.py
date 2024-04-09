import dataclasses
import datetime as dt
import json
import uuid

from asgiref.sync import sync_to_async
from dlt.common.schema.typing import TSchemaTables
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

# TODO: remove dependency
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.data_imports.pipelines.helpers import aupdate_job_count
from posthog.temporal.data_imports.pipelines.schemas import PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING
from posthog.temporal.data_imports.pipelines.zendesk.credentials import ZendeskCredentialsToken
from posthog.warehouse.data_load.source_templates import create_warehouse_templates_for_source

from posthog.warehouse.data_load.validate_schema import validate_schema_and_update_table
from posthog.temporal.data_imports.pipelines.pipeline import DataImportPipeline, PipelineInputs
from posthog.warehouse.external_data_source.jobs import (
    create_external_data_job,
    update_external_job_status,
)
from posthog.warehouse.models import (
    ExternalDataJob,
    get_active_schemas_for_source_id,
    sync_old_schemas_with_new_schemas,
    ExternalDataSource,
    get_external_data_job,
)
from posthog.warehouse.models.external_data_schema import get_postgres_schemas
from posthog.temporal.common.logger import bind_temporal_worker_logger
from typing import Dict, Tuple
import asyncio
from django.conf import settings


@dataclasses.dataclass
class CreateExternalDataJobInputs:
    team_id: int
    external_data_source_id: uuid.UUID


@activity.defn
async def create_external_data_job_model(inputs: CreateExternalDataJobInputs) -> Tuple[str, list[Tuple[str, str]]]:
    run = await sync_to_async(create_external_data_job)(
        team_id=inputs.team_id,
        external_data_source_id=inputs.external_data_source_id,
        workflow_id=activity.info().workflow_id,
    )

    source = await sync_to_async(ExternalDataSource.objects.get)(
        team_id=inputs.team_id, id=inputs.external_data_source_id
    )
    source.status = "Running"
    await sync_to_async(source.save)()

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

    await sync_to_async(sync_old_schemas_with_new_schemas)(  # type: ignore
        schemas_to_sync,
        source_id=inputs.external_data_source_id,
        team_id=inputs.team_id,
    )

    schemas = await sync_to_async(get_active_schemas_for_source_id)(
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
    await sync_to_async(update_external_job_status)(
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
    schemas: list[Tuple[str, str]]
    table_schema: TSchemaTables
    table_row_counts: Dict[str, int]


@activity.defn
async def validate_schema_activity(inputs: ValidateSchemaInputs) -> None:
    await validate_schema_and_update_table(
        run_id=inputs.run_id,
        team_id=inputs.team_id,
        schemas=inputs.schemas,
        table_schema=inputs.table_schema,
        table_row_counts=inputs.table_row_counts,
    )

    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)
    logger.info(
        f"Validated schema for external data job {inputs.run_id}",
    )


@dataclasses.dataclass
class CreateSourceTemplateInputs:
    team_id: int
    run_id: str


@activity.defn
async def create_source_templates(inputs: CreateSourceTemplateInputs) -> None:
    await create_warehouse_templates_for_source(team_id=inputs.team_id, run_id=inputs.run_id)


@dataclasses.dataclass
class ExternalDataWorkflowInputs:
    team_id: int
    external_data_source_id: uuid.UUID


@dataclasses.dataclass
class ExternalDataJobInputs:
    team_id: int
    source_id: uuid.UUID
    run_id: str
    schemas: list[Tuple[str, str]]


@activity.defn
async def run_external_data_job(inputs: ExternalDataJobInputs) -> Tuple[TSchemaTables, Dict[str, int]]:  # noqa: F821
    model: ExternalDataJob = await get_external_data_job(
        job_id=inputs.run_id,
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

    endpoints = [schema[1] for schema in inputs.schemas]

    source = None
    if model.pipeline.source_type == ExternalDataSource.Type.STRIPE:
        from posthog.temporal.data_imports.pipelines.stripe.helpers import stripe_source

        stripe_secret_key = model.pipeline.job_inputs.get("stripe_secret_key", None)
        account_id = model.pipeline.job_inputs.get("stripe_account_id", None)
        # Cludge: account_id should be checked here too but can deal with nulls
        # until we require re update of account_ids in stripe so they're all store
        if not stripe_secret_key:
            raise ValueError(f"Stripe secret key not found for job {model.id}")
        source = stripe_source(
            api_key=stripe_secret_key,
            account_id=account_id,
            endpoints=tuple(endpoints),
            team_id=inputs.team_id,
            job_id=inputs.run_id,
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
            endpoints=tuple(endpoints),
        )
    elif model.pipeline.source_type == ExternalDataSource.Type.POSTGRES:
        from posthog.temporal.data_imports.pipelines.postgres import postgres_source

        host = model.pipeline.job_inputs.get("host")
        port = model.pipeline.job_inputs.get("port")
        user = model.pipeline.job_inputs.get("user")
        password = model.pipeline.job_inputs.get("password")
        database = model.pipeline.job_inputs.get("database")
        schema = model.pipeline.job_inputs.get("schema")

        source = postgres_source(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            sslmode="prefer" if settings.TEST or settings.DEBUG else "require",
            schema=schema,
            table_names=endpoints,
        )
    elif model.pipeline.source_type == ExternalDataSource.Type.ZENDESK:
        from posthog.temporal.data_imports.pipelines.zendesk.helpers import zendesk_support

        credentials = ZendeskCredentialsToken()
        credentials.token = model.pipeline.job_inputs.get("zendesk_api_key")
        credentials.subdomain = model.pipeline.job_inputs.get("zendesk_subdomain")
        credentials.email = model.pipeline.job_inputs.get("zendesk_email_address")

        data_support = zendesk_support(credentials=credentials, endpoints=tuple(endpoints), team_id=inputs.team_id)
        # Uncomment to support zendesk chat and talk
        # data_chat = zendesk_chat()
        # data_talk = zendesk_talk()

        source = data_support
    else:
        raise ValueError(f"Source type {model.pipeline.source_type} not supported")

    # Temp background heartbeat for now
    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(10)
            activity.heartbeat()

    heartbeat_task = asyncio.create_task(heartbeat())

    try:
        table_row_counts = await DataImportPipeline(job_inputs, source, logger).run()
        total_rows_synced = sum(table_row_counts.values())

        await aupdate_job_count(inputs.run_id, inputs.team_id, total_rows_synced)
    finally:
        heartbeat_task.cancel()
        await asyncio.wait([heartbeat_task])

    return source.schema.tables, table_row_counts


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

            table_schemas, table_row_counts = await workflow.execute_activity(
                run_external_data_job,
                job_inputs,
                start_to_close_timeout=dt.timedelta(hours=30),
                retry_policy=RetryPolicy(maximum_attempts=5),
                heartbeat_timeout=dt.timedelta(minutes=1),
            )

            # check schema first
            validate_inputs = ValidateSchemaInputs(
                run_id=run_id,
                team_id=inputs.team_id,
                schemas=schemas,
                table_schema=table_schemas,
                table_row_counts=table_row_counts,
            )

            await workflow.execute_activity(
                validate_schema_activity,
                validate_inputs,
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            # Create source templates
            await workflow.execute_activity(
                create_source_templates,
                CreateSourceTemplateInputs(team_id=inputs.team_id, run_id=run_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
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
