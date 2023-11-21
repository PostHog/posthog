import json
import dataclasses
import uuid
import datetime as dt
from typing import List
from posthog.warehouse.data_load.pipeline import (
    PIPELINE_TYPE_INPUTS_MAPPING,
    PIPELINE_TYPE_RUN_MAPPING,
    move_draft_to_production,
    SourceSchema,
)
from posthog.warehouse.data_load.sync_table import is_schema_valid, SchemaValidationError

from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.external_data_source.jobs import (
    create_external_data_job,
    update_external_job_status,
    get_external_data_source,
)
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.temporal.workflows.base import PostHogWorkflow
from posthog.temporal.heartbeat import HeartbeatDetails
from temporalio import activity, workflow, exceptions
from temporalio.common import RetryPolicy
from asgiref.sync import sync_to_async


@dataclasses.dataclass
class CreateExternalDataJobInputs:
    team_id: int
    external_data_source_id: str


@activity.defn
async def create_external_data_job_model(inputs: CreateExternalDataJobInputs) -> str:
    run = await sync_to_async(create_external_data_job)(
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
    await sync_to_async(update_external_job_status)(
        run_id=uuid.UUID(inputs.id),
        status=inputs.status,
        latest_error=inputs.latest_error,
    )  # type: ignore


@dataclasses.dataclass
class ValidateSchemaInputs:
    source_schemas: List[SourceSchema]
    external_data_source_id: str
    create: bool


@activity.defn
async def validate_schema_activity(inputs: ValidateSchemaInputs) -> bool:
    return await sync_to_async(is_schema_valid)(
        source_schemas=inputs.source_schemas,
        external_data_source_id=inputs.external_data_source_id,
        create=inputs.create,
    )


@dataclasses.dataclass
class MoveDraftToProductionExternalDataJobInputs:
    team_id: int
    external_data_source_id: str


@activity.defn
async def move_draft_to_production_activity(inputs: MoveDraftToProductionExternalDataJobInputs) -> None:
    await sync_to_async(move_draft_to_production)(
        team_id=inputs.team_id,
        external_data_source_id=inputs.external_data_source_id,
    )


@dataclasses.dataclass
class ExternalDataJobInputs:
    team_id: int
    external_data_source_id: str


@activity.defn
async def run_external_data_job(inputs: ExternalDataJobInputs) -> List[SourceSchema]:
    model: ExternalDataSource = await sync_to_async(get_external_data_source)(
        team_id=inputs.team_id,
        external_data_source_id=inputs.external_data_source_id,
    )

    job_inputs = PIPELINE_TYPE_INPUTS_MAPPING[model.source_type](
        team_id=inputs.team_id, job_type=model.source_type, dataset_name=model.draft_folder_path, **model.job_inputs
    )
    job_fn = PIPELINE_TYPE_RUN_MAPPING[model.source_type]

    async_job_fn = sync_to_async(job_fn)

    heartbeat_details = HeartbeatDetails()
    func = heartbeat_details.make_activity_heartbeat_while_running(async_job_fn, dt.timedelta(seconds=1))

    return await func(job_inputs)


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
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        update_inputs = UpdateExternalDataJobStatusInputs(
            id=run_id, run_id=run_id, status=ExternalDataJob.Status.COMPLETED, latest_error=None
        )

        # TODO: can make this a child workflow for separate worker pool
        try:
            source_schemas = await workflow.execute_activity(
                run_external_data_job,
                inputs,
                start_to_close_timeout=dt.timedelta(minutes=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
                heartbeat_timeout=dt.timedelta(minutes=2),
            )

            # check schema first
            validate_inputs = ValidateSchemaInputs(
                source_schemas=source_schemas, external_data_source_id=inputs.external_data_source_id, create=False
            )

            await workflow.execute_activity(
                validate_schema_activity,
                validate_inputs,
                start_to_close_timeout=dt.timedelta(minutes=2),
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

            move_inputs = MoveDraftToProductionExternalDataJobInputs(
                team_id=inputs.team_id,
                external_data_source_id=inputs.external_data_source_id,
            )

        except exceptions.ActivityError as e:
            if isinstance(e.cause, exceptions.CancelledError):
                update_inputs.status = ExternalDataJob.Status.CANCELLED
            else:
                update_inputs.status = ExternalDataJob.Status.FAILED

            update_inputs.latest_error = str(e.cause)
            raise
        except Exception as e:
            if isinstance(e, SchemaValidationError):
                update_inputs.latest_error = "Schema validation failed"
            else:
                update_inputs.latest_error = "An unexpected error has ocurred"

            update_inputs.status = ExternalDataJob.Status.FAILED
            raise
        else:
            await workflow.execute_activity(
                move_draft_to_production_activity,
                move_inputs,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        finally:
            await workflow.execute_activity(
                update_external_data_job_model,
                update_inputs,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
