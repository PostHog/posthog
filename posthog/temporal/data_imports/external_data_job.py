import dataclasses
import datetime as dt
import json

from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

# TODO: remove dependency
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.data_imports.workflow_activities.check_billing_limits import (
    CheckBillingLimitsActivityInputs,
    check_billing_limits_activity,
)
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

from posthog.warehouse.external_data_source.jobs import (
    aupdate_external_job_status,
)
from posthog.warehouse.models import (
    ExternalDataJob,
    get_active_schemas_for_source_id,
    ExternalDataSource,
)
from posthog.temporal.common.logger import bind_temporal_worker_logger
from posthog.warehouse.models.external_data_schema import aupdate_should_sync


Non_Retryable_Schema_Errors = [
    "NoSuchTableError",
    "401 Client Error: Unauthorized for url: https://api.stripe.com",
    "403 Client Error: Forbidden for url: https://api.stripe.com",
]


@dataclasses.dataclass
class UpdateExternalDataJobStatusInputs:
    id: str
    team_id: int
    run_id: str
    schema_id: str
    status: str
    internal_error: str | None
    latest_error: str | None


@activity.defn
async def update_external_data_job_model(inputs: UpdateExternalDataJobStatusInputs) -> None:
    logger = await bind_temporal_worker_logger(team_id=inputs.team_id)

    if inputs.internal_error:
        logger.exception(
            f"External data job failed for external data schema {inputs.schema_id} with error: {inputs.internal_error}"
        )

        has_non_retryable_error = any(error in inputs.internal_error for error in Non_Retryable_Schema_Errors)
        if has_non_retryable_error:
            logger.info("Schema has a non-retryable error - turning off syncing")
            await aupdate_should_sync(schema_id=inputs.schema_id, team_id=inputs.team_id, should_sync=False)

    await aupdate_external_job_status(
        job_id=inputs.id,
        status=inputs.status,
        latest_error=inputs.latest_error,
        team_id=inputs.team_id,
    )

    logger.info(
        f"Updated external data job with for external data source {inputs.run_id} to status {inputs.status}",
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
            team_id=inputs.team_id,
            schema_id=inputs.external_data_schema_id,
            source_id=inputs.external_data_source_id,
        )

        # TODO: split out the creation of the external data job model from schema getting to seperate out exception handling
        job_id, incremental = await workflow.execute_activity(
            create_external_data_job_model_activity,
            create_external_data_job_inputs,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=3,
                non_retryable_error_types=["NotNullViolation", "IntegrityError", "BaseSSHTunnelForwarderError"],
            ),
        )

        # Check billing limits
        hit_billing_limit = await workflow.execute_activity(
            check_billing_limits_activity,
            CheckBillingLimitsActivityInputs(job_id=job_id, team_id=inputs.team_id),
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=3,
            ),
        )

        if hit_billing_limit:
            return

        update_inputs = UpdateExternalDataJobStatusInputs(
            id=job_id,
            run_id=job_id,
            status=ExternalDataJob.Status.COMPLETED,
            latest_error=None,
            internal_error=None,
            team_id=inputs.team_id,
            schema_id=str(inputs.external_data_schema_id),
        )

        try:
            job_inputs = ImportDataActivityInputs(
                team_id=inputs.team_id,
                run_id=job_id,
                schema_id=inputs.external_data_schema_id,
                source_id=inputs.external_data_source_id,
            )

            timeout_params = (
                {"start_to_close_timeout": dt.timedelta(weeks=1), "retry_policy": RetryPolicy(maximum_attempts=1)}
                if incremental
                else {"start_to_close_timeout": dt.timedelta(hours=5), "retry_policy": RetryPolicy(maximum_attempts=3)}
            )

            await workflow.execute_activity(
                import_data_activity,
                job_inputs,
                heartbeat_timeout=dt.timedelta(minutes=2),
                **timeout_params,
            )  # type: ignore

            # Create source templates
            await workflow.execute_activity(
                create_source_templates,
                CreateSourceTemplateInputs(team_id=inputs.team_id, run_id=job_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

        except exceptions.ActivityError as e:
            update_inputs.status = ExternalDataJob.Status.FAILED
            update_inputs.internal_error = str(e.cause)
            update_inputs.latest_error = str(e.cause)
            raise
        except Exception as e:
            # Catch all
            update_inputs.internal_error = str(e)
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
