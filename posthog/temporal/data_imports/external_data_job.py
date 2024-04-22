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
from posthog.temporal.utils import ExternalDataWorkflowInputs
from posthog.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityInputs,
    create_external_data_job_model_activity,
)
from posthog.temporal.data_imports.workflow_activities.import_data import ImportDataActivityInputs, import_data_activity
from posthog.warehouse.data_load.service import (
    a_delete_external_data_schedule,
    a_external_data_workflow_exists,
    a_sync_external_data_job_workflow,
    a_trigger_external_data_workflow,
)
from posthog.warehouse.data_load.source_templates import create_warehouse_templates_for_source

from posthog.warehouse.data_load.validate_schema import validate_schema_and_update_table
from posthog.warehouse.external_data_source.jobs import (
    update_external_job_status,
)
from posthog.warehouse.models import (
    ExternalDataJob,
    get_active_schemas_for_source_id,
    ExternalDataSource,
)
from posthog.temporal.common.logger import bind_temporal_worker_logger
from typing import Dict


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
    schema_id: uuid.UUID
    table_schema: TSchemaTables
    table_row_counts: Dict[str, int]


@activity.defn
async def validate_schema_activity(inputs: ValidateSchemaInputs) -> None:
    await validate_schema_and_update_table(
        run_id=inputs.run_id,
        team_id=inputs.team_id,
        schema_id=inputs.schema_id,
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


@activity.defn
async def check_schedule_activity(inputs: ExternalDataWorkflowInputs) -> bool:
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

    # Creates schedules for all schemas if they don't exist yet, and then remove itself as a source schedule
    if inputs.external_data_schema_id is None:
        logger.info("Schema ID is none, creating schedules for schemas...")
        schemas = await get_active_schemas_for_source_id(
            team_id=inputs.team_id, source_id=inputs.external_data_source_id
        )
        for schema in schemas:
            if await a_external_data_workflow_exists(schema.id):
                await a_trigger_external_data_workflow(schema)
                logger.info(f"Schedule exists for schema {schema.id}. Triggered schedule")
            else:
                await a_sync_external_data_job_workflow(schema, create=True)
                logger.info(f"Created schedule for schema {schema.id}")
        # Delete the source schedule in favour of the schema schedules
        await a_delete_external_data_schedule(ExternalDataSource(id=inputs.external_data_source_id))
        logger.info(f"Deleted schedule for source {inputs.external_data_source_id}")
        return True

    logger.info("Schema ID is set. Continuing...")
    return False


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

        should_exit = await workflow.execute_activity(
            check_schedule_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

        if should_exit:
            return

        assert inputs.external_data_schema_id is not None

        # create external data job and trigger activity
        create_external_data_job_inputs = CreateExternalDataJobModelActivityInputs(
            team_id=inputs.team_id, schema_id=inputs.external_data_schema_id, source_id=inputs.external_data_source_id
        )

        run_id = await workflow.execute_activity(
            create_external_data_job_model_activity,
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
            job_inputs = ImportDataActivityInputs(
                team_id=inputs.team_id,
                run_id=run_id,
                schema_id=inputs.external_data_schema_id,
                source_id=inputs.external_data_source_id,
            )

            table_schemas, table_row_counts = await workflow.execute_activity(
                import_data_activity,
                job_inputs,
                start_to_close_timeout=dt.timedelta(hours=30),
                retry_policy=RetryPolicy(maximum_attempts=5),
                heartbeat_timeout=dt.timedelta(minutes=1),
            )

            # check schema first
            validate_inputs = ValidateSchemaInputs(
                run_id=run_id,
                team_id=inputs.team_id,
                schema_id=inputs.external_data_schema_id,
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
