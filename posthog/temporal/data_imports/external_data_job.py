import dataclasses
import datetime as dt
import json
import uuid

from asgiref.sync import sync_to_async
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

# TODO: remove dependency
from posthog.temporal.batch_exports.base import PostHogWorkflow
from posthog.temporal.data_imports.pipelines.stripe.stripe_pipeline import (
    PIPELINE_TYPE_INPUTS_MAPPING,
    PIPELINE_TYPE_RUN_MAPPING,
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.warehouse.data_load.validate_schema import validate_schema_and_update_table
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
from posthog.temporal.common.logger import bind_temporal_worker_logger
from typing import Tuple


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

    # Sync schemas if they have changed
    await sync_to_async(sync_old_schemas_with_new_schemas)(  # type: ignore
        list(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[source.source_type]),  # type: ignore
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

    job_inputs = PIPELINE_TYPE_INPUTS_MAPPING[model.pipeline.source_type](
        source_id=inputs.source_id,
        schemas=inputs.schemas,
        run_id=inputs.run_id,
        team_id=inputs.team_id,
        job_type=model.pipeline.source_type,
        dataset_name=model.folder_path,
        **model.pipeline.job_inputs,
    )
    job_fn = PIPELINE_TYPE_RUN_MAPPING[model.pipeline.source_type]

    await job_fn(job_inputs)


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

            # TODO: can make this a child workflow for separate worker pool
            await workflow.execute_activity(
                run_external_data_job,
                job_inputs,
                start_to_close_timeout=dt.timedelta(minutes=120),
                retry_policy=RetryPolicy(maximum_attempts=10),
                heartbeat_timeout=dt.timedelta(seconds=60),
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
