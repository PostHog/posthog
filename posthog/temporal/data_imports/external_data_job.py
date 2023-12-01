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
)
from posthog.warehouse.data_load.sync_table import SchemaValidationError, is_schema_valid, move_draft_to_production
from posthog.warehouse.external_data_source.jobs import (
    create_external_data_job,
    get_external_data_source,
    update_external_job_status,
)
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_source import ExternalDataSource


@dataclasses.dataclass
class CreateExternalDataJobInputs:
    team_id: int
    external_data_source_id: str


@activity.defn
async def create_external_data_job_model(inputs: CreateExternalDataJobInputs) -> str:
    run = await sync_to_async(create_external_data_job)(  # type: ignore
        team_id=inputs.team_id,
        external_data_source_id=inputs.external_data_source_id,
    )

    return str(run.id)


@dataclasses.dataclass
class UpdateExternalDataJobStatusInputs:
    id: str
    run_id: str
    status: str
    latest_error: str | None


@activity.defn
async def update_external_data_job_model(inputs: UpdateExternalDataJobStatusInputs) -> None:
    await sync_to_async(update_external_job_status)(  # type: ignore
        run_id=uuid.UUID(inputs.id),
        status=inputs.status,
        latest_error=inputs.latest_error,
    )


@dataclasses.dataclass
class ValidateSchemaInputs:
    external_data_source_id: str
    create: bool


@activity.defn
async def validate_schema_activity(inputs: ValidateSchemaInputs) -> bool:
    return await sync_to_async(is_schema_valid)(  # type: ignore
        external_data_source_id=inputs.external_data_source_id,
        create=inputs.create,
    )


@dataclasses.dataclass
class MoveDraftToProductionExternalDataJobInputs:
    team_id: int
    external_data_source_id: str


@activity.defn
async def move_draft_to_production_activity(inputs: MoveDraftToProductionExternalDataJobInputs) -> None:
    await sync_to_async(move_draft_to_production)(  # type: ignore
        team_id=inputs.team_id,
        external_data_source_id=inputs.external_data_source_id,
    )


@dataclasses.dataclass
class ExternalDataJobInputs:
    team_id: int
    external_data_source_id: str


@activity.defn
async def run_external_data_job(inputs: ExternalDataJobInputs) -> None:
    model: ExternalDataSource = await sync_to_async(get_external_data_source)(  # type: ignore
        team_id=inputs.team_id,
        external_data_source_id=inputs.external_data_source_id,
    )

    job_inputs = PIPELINE_TYPE_INPUTS_MAPPING[model.source_type](
        source_id=inputs.external_data_source_id,
        team_id=inputs.team_id,
        job_type=model.source_type,
        dataset_name=model.draft_folder_path,
        **model.job_inputs,
    )
    job_fn = PIPELINE_TYPE_RUN_MAPPING[model.source_type]

    await job_fn(job_inputs)


# TODO: update retry policies
@workflow.defn(name="external-data-job")
class ExternalDataJobWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExternalDataJobInputs:
        loaded = json.loads(inputs[0])
        return ExternalDataJobInputs(**loaded)

    @workflow.run
    async def run(self, inputs: ExternalDataJobInputs):
        # create external data job and trigger activity
        create_external_data_job_inputs = CreateExternalDataJobInputs(
            team_id=inputs.team_id,
            external_data_source_id=inputs.external_data_source_id,
        )

        run_id = await workflow.execute_activity(
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
            id=run_id, run_id=run_id, status=ExternalDataJob.Status.COMPLETED, latest_error=None
        )

        try:
            # TODO: can make this a child workflow for separate worker pool
            await workflow.execute_activity(
                run_external_data_job,
                inputs,
                start_to_close_timeout=dt.timedelta(minutes=60),
                retry_policy=RetryPolicy(maximum_attempts=10),
                heartbeat_timeout=dt.timedelta(seconds=20),
            )

            # check schema first
            validate_inputs = ValidateSchemaInputs(external_data_source_id=inputs.external_data_source_id, create=False)

            await workflow.execute_activity(
                validate_schema_activity,
                validate_inputs,
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            move_inputs = MoveDraftToProductionExternalDataJobInputs(
                team_id=inputs.team_id,
                external_data_source_id=inputs.external_data_source_id,
            )

            await workflow.execute_activity(
                move_draft_to_production_activity,
                move_inputs,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            # if not errors, then create the schema
            validate_inputs.create = True
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

            update_inputs.latest_error = str(e.cause)
            raise
        except SchemaValidationError as e:
            update_inputs.latest_error = str(e)
            update_inputs.status = ExternalDataJob.Status.FAILED
            raise
        except Exception:
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
                    non_retryable_error_types=["NotNullViolation", "IntegrityError"],
                ),
            )
