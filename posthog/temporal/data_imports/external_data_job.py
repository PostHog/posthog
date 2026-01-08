import re
import json
import typing
import datetime as dt
import dataclasses

from django.conf import settings
from django.db import close_old_connections

import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

# TODO: remove dependency
from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.schedule import trigger_schedule_buffer_one
from posthog.temporal.data_imports.metrics import get_data_import_finished_metric
from posthog.temporal.data_imports.row_tracking import finish_row_tracking, get_rows
from posthog.temporal.data_imports.sources import SourceRegistry
from posthog.temporal.data_imports.sources.common.base import ResumableSource
from posthog.temporal.data_imports.workflow_activities.calculate_table_size import (
    CalculateTableSizeActivityInputs,
    calculate_table_size_activity,
)
from posthog.temporal.data_imports.workflow_activities.check_billing_limits import (
    CheckBillingLimitsActivityInputs,
    check_billing_limits_activity,
)
from posthog.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityInputs,
    create_external_data_job_model_activity,
)
from posthog.temporal.data_imports.workflow_activities.et_activities import (
    ExtractBatchInputs,
    StartLoadWorkflowInputs,
    UpdateETTrackingInputs,
    extract_and_transform_batch_activity,
    start_load_workflow_activity,
    update_et_tracking_activity,
)
from posthog.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
    import_data_activity_sync,
)
from posthog.temporal.data_imports.workflow_activities.sync_new_schemas import (
    SyncNewSchemasActivityInputs,
    sync_new_schemas_activity,
)
from posthog.temporal.ducklake.ducklake_copy_data_imports_workflow import (
    DataImportsDuckLakeCopyInputs,
    DuckLakeCopyDataImportsWorkflow,
)
from posthog.temporal.utils import ExternalDataWorkflowInputs
from posthog.utils import get_machine_id

from products.data_warehouse.backend.data_load.source_templates import create_warehouse_templates_for_source
from products.data_warehouse.backend.external_data_source.jobs import update_external_job_status
from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from products.data_warehouse.backend.models.external_data_schema import update_should_sync
from products.data_warehouse.backend.types import ExternalDataSourceType

LOGGER = get_logger(__name__)

Any_Source_Errors: dict[str, str | None] = {
    "Could not establish session to SSH gateway": None,
    "Primary key required for incremental syncs": None,
    "The primary keys for this table are not unique": None,
    "Integration matching query does not exist": None,
}


@dataclasses.dataclass
class UpdateExternalDataJobStatusInputs:
    team_id: int
    job_id: str | None
    schema_id: str
    source_id: str
    status: str
    internal_error: str | None
    latest_error: str | None
    rows_synced: int | None = None

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
            "schema_id": self.schema_id,
            "source_id": self.source_id,
            "status": self.status,
        }


@activity.defn
def update_external_data_job_model(inputs: UpdateExternalDataJobStatusInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    close_old_connections()

    rows_tracked = get_rows(inputs.team_id, inputs.schema_id)
    if rows_tracked > 0 and inputs.status == ExternalDataJob.Status.COMPLETED:
        msg = f"Rows tracked is greater than 0 on a COMPLETED job. rows_tracked={rows_tracked}"
        logger.debug(msg)
        capture_exception(Exception(msg))

    finish_row_tracking(inputs.team_id, inputs.schema_id)

    if inputs.job_id is None:
        job: ExternalDataJob | None = (
            ExternalDataJob.objects.filter(schema_id=inputs.schema_id, status=ExternalDataJob.Status.RUNNING)
            .order_by("-created_at")
            .first()
        )
        if job is None:
            logger.info("No job to update status on")
            return

        job_id = str(job.pk)
    else:
        job_id = inputs.job_id

    if inputs.internal_error:
        logger.exception(
            f"External data job failed for external data schema {inputs.schema_id} on job {inputs.job_id} with error: {inputs.internal_error}"
        )

        internal_error_normalized = re.sub("[\n\r\t]", " ", inputs.internal_error)

        source: ExternalDataSource = ExternalDataSource.objects.get(pk=inputs.source_id)
        source_cls = SourceRegistry.get_source(ExternalDataSourceType(source.source_type))
        non_retryable_errors = source_cls.get_non_retryable_errors()

        if len(non_retryable_errors) == 0:
            non_retryable_errors = Any_Source_Errors
        else:
            non_retryable_errors = {**non_retryable_errors, **Any_Source_Errors}

        has_non_retryable_error = any(error in internal_error_normalized for error in non_retryable_errors.keys())
        if has_non_retryable_error:
            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="schema non-retryable error",
                properties={
                    "schemaId": inputs.schema_id,
                    "sourceId": inputs.source_id,
                    "sourceType": source.source_type,
                    "jobId": inputs.job_id,
                    "teamId": inputs.team_id,
                    "error": inputs.internal_error,
                },
            )
            update_should_sync(schema_id=inputs.schema_id, team_id=inputs.team_id, should_sync=False)

            friendly_errors = [
                friendly_error
                for error, friendly_error in non_retryable_errors.items()
                if error in internal_error_normalized
            ]

            if friendly_errors and friendly_errors[0] is not None:
                logger.exception(friendly_errors[0])
                inputs.latest_error = friendly_errors[0]

    job = update_external_job_status(
        job_id=job_id,
        status=ExternalDataJob.Status(inputs.status),
        latest_error=inputs.latest_error,
        team_id=inputs.team_id,
    )

    job.finished_at = dt.datetime.now(dt.UTC)
    if inputs.rows_synced is not None:
        job.rows_synced = inputs.rows_synced
    job.save()

    logger.info(
        f"Updated external data job with for external data source {job_id} to status {inputs.status}",
    )


@dataclasses.dataclass
class CreateSourceTemplateInputs:
    team_id: int
    run_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "run_id": self.run_id,
        }


@activity.defn
def create_source_templates(inputs: CreateSourceTemplateInputs) -> None:
    create_warehouse_templates_for_source(team_id=inputs.team_id, run_id=inputs.run_id)


@activity.defn
def trigger_schedule_buffer_one_activity(schedule_id: str) -> None:
    schema = ExternalDataSchema.objects.get(id=schedule_id)
    logger = LOGGER.bind(team_id=schema.team.pk)

    logger.debug(f"Triggering temporal schedule {schedule_id} with policy 'buffer one'")

    temporal = sync_connect()
    trigger_schedule_buffer_one(temporal, schedule_id)


@dataclasses.dataclass
class ETLSeparationGateInputs:
    team_id: int
    schema_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {"team_id": self.team_id, "schema_id": self.schema_id}


@activity.defn
def etl_separation_gate_activity(inputs: ETLSeparationGateInputs) -> bool:
    """
    Evaluate whether to use the new ET+L separation workflow.
    Only incremental syncs behind the feature flag will use the new path.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    return True

    try:
        schema = ExternalDataSchema.objects.get(id=inputs.schema_id)
    except ExternalDataSchema.DoesNotExist:
        logger.exception("Schema does not exist when evaluating ETL separation gate")
        return False

    if not schema.is_incremental:
        logger.debug("Non-incremental sync, using V2 pipeline version")
        return False

    logger.debug("Incremental sync, evaluating feature flag for V3 pipeline version")

    try:
        team = Team.objects.only("uuid", "organization_id").get(id=inputs.team_id)
    except Team.DoesNotExist:
        logger.exception("Team does not exist when evaluating ETL separation gate")
        return False

    try:
        return posthoganalytics.feature_enabled(
            "data-warehouse-etl-separation",
            str(team.uuid),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {
                    "id": str(team.organization_id),
                },
                "project": {
                    "id": str(team.id),
                },
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception as error:
        logger.warning(
            f"Failed to evaluate ETL separation feature flag, defaulting to legacy path for team {inputs.team_id}",
            error=str(error),
        )
        capture_exception(error)
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
        assert inputs.external_data_schema_id is not None

        update_inputs = UpdateExternalDataJobStatusInputs(
            job_id=None,
            status=ExternalDataJob.Status.COMPLETED,
            latest_error=None,
            internal_error=None,
            team_id=inputs.team_id,
            schema_id=str(inputs.external_data_schema_id),
            source_id=str(inputs.external_data_source_id),
        )

        source_type = None
        use_etl_separation = False
        try:
            # create external data job and trigger activity
            create_external_data_job_inputs = CreateExternalDataJobModelActivityInputs(
                team_id=inputs.team_id,
                schema_id=inputs.external_data_schema_id,
                source_id=inputs.external_data_source_id,
                billable=inputs.billable,
            )

            job_id, incremental_or_append, source_type = await workflow.execute_activity(
                create_external_data_job_model_activity,
                create_external_data_job_inputs,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    maximum_attempts=1,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError"],
                ),
            )

            update_inputs.job_id = job_id

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
                update_inputs.status = ExternalDataJob.Status.BILLING_LIMIT_REACHED
                return

            await workflow.execute_activity(
                sync_new_schemas_activity,
                SyncNewSchemasActivityInputs(source_id=str(inputs.external_data_source_id), team_id=inputs.team_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=3,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError", "BaseSSHTunnelForwarderError"],
                ),
            )

            use_etl_separation = await workflow.execute_activity(
                etl_separation_gate_activity,
                ETLSeparationGateInputs(team_id=inputs.team_id, schema_id=str(inputs.external_data_schema_id)),
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            is_resumable_source = False
            if source_type is not None:
                source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
                is_resumable_source = isinstance(source, ResumableSource)

            timeout_params = (
                {
                    "start_to_close_timeout": dt.timedelta(weeks=1),
                    "retry_policy": RetryPolicy(
                        maximum_attempts=9, non_retryable_error_types=["NonRetryableException"]
                    ),
                }
                if incremental_or_append or is_resumable_source
                else {
                    "start_to_close_timeout": dt.timedelta(hours=24),
                    "retry_policy": RetryPolicy(
                        maximum_attempts=3, non_retryable_error_types=["NonRetryableException"]
                    ),
                }
            )

            if use_etl_separation:
                # Generate Load workflow ID
                et_workflow_id = workflow.info().workflow_id
                now = workflow.now()
                timestamp = now.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
                load_workflow_id = f"load-{inputs.external_data_schema_id}-{timestamp}"
                load_workflow_started = False
                et_completed_successfully = False

                try:
                    await workflow.execute_activity(
                        update_et_tracking_activity,
                        UpdateETTrackingInputs(
                            job_id=job_id,
                            et_workflow_id=et_workflow_id,
                            l_workflow_id=load_workflow_id,
                            et_started_at=True,
                            pipeline_version=ExternalDataJob.PipelineVersion.V3,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=1),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )

                    # Start Load workflow (it will wait for signals)
                    await workflow.execute_activity(
                        start_load_workflow_activity,
                        StartLoadWorkflowInputs(
                            workflow_id=load_workflow_id,
                            team_id=inputs.team_id,
                            source_id=str(inputs.external_data_source_id),
                            schema_id=str(inputs.external_data_schema_id),
                            job_id=job_id,
                            source_type=source_type,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=2),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    load_workflow_started = True

                    et_result = await workflow.execute_activity(
                        extract_and_transform_batch_activity,
                        ExtractBatchInputs(
                            team_id=inputs.team_id,
                            source_id=inputs.external_data_source_id,
                            schema_id=inputs.external_data_schema_id,
                            job_id=job_id,
                            temp_s3_prefix=None,
                            reset_pipeline=inputs.reset_pipeline or False,
                            load_workflow_id=load_workflow_id,
                        ),
                        heartbeat_timeout=dt.timedelta(minutes=2),
                        **timeout_params,
                    )

                    if et_result.manifest_path:
                        await workflow.execute_activity(
                            update_et_tracking_activity,
                            UpdateETTrackingInputs(
                                job_id=job_id,
                                temp_s3_prefix=et_result.temp_s3_prefix,
                                manifest_path=et_result.manifest_path,
                                et_finished_at=True,
                                et_rows_extracted=et_result.row_count,
                            ),
                            start_to_close_timeout=dt.timedelta(minutes=1),
                            retry_policy=RetryPolicy(maximum_attempts=2),
                        )

                    et_completed_successfully = True
                finally:
                    if load_workflow_started and not et_completed_successfully:
                        try:
                            cancel_handle = workflow.get_external_workflow_handle(load_workflow_id)
                            await cancel_handle.cancel()
                        except Exception as e:
                            workflow.logger.warning(f"Failed to cancel Load workflow {load_workflow_id}: {e}")
            else:
                job_inputs = ImportDataActivityInputs(
                    team_id=inputs.team_id,
                    run_id=job_id,
                    schema_id=inputs.external_data_schema_id,
                    source_id=inputs.external_data_source_id,
                    reset_pipeline=inputs.reset_pipeline,
                )

                await workflow.execute_activity(
                    import_data_activity_sync,
                    job_inputs,
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    **timeout_params,
                )

                # Create source templates
                await workflow.execute_activity(
                    create_source_templates,
                    CreateSourceTemplateInputs(team_id=inputs.team_id, run_id=job_id),
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )

                await workflow.execute_activity(
                    calculate_table_size_activity,
                    CalculateTableSizeActivityInputs(
                        team_id=inputs.team_id, schema_id=str(inputs.external_data_schema_id), job_id=job_id
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

                # Start DuckLake copy workflow as a child (fire-and-forget)
                await workflow.start_child_workflow(
                    DuckLakeCopyDataImportsWorkflow.run,
                    DataImportsDuckLakeCopyInputs(
                        team_id=inputs.team_id,
                        job_id=job_id,
                        schema_ids=[inputs.external_data_schema_id],
                    ),
                    id=f"ducklake-copy-data-imports-{job_id}",
                    task_queue=settings.DUCKLAKE_TASK_QUEUE,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )

        except exceptions.ActivityError as e:
            if isinstance(e.cause, exceptions.ApplicationError) and e.cause.type == "WorkerShuttingDownError":
                # Check if this is a WorkerShuttingDownError - implement Buffer One retry
                schedule_id = str(inputs.external_data_schema_id)
                await workflow.execute_activity(
                    trigger_schedule_buffer_one_activity,
                    schedule_id,
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            elif (
                isinstance(e.cause, exceptions.ApplicationError)
                and e.cause.type == "BillingLimitsWillBeReachedException"
            ):
                # Check if this is a BillingLimitsWillBeReachedException - update the job status
                update_inputs.status = ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW
            elif isinstance(e.cause, exceptions.ApplicationError) and e.cause.type == "NonRetryableException":
                update_inputs.status = ExternalDataJob.Status.FAILED
                update_inputs.internal_error = str(e.cause)
                update_inputs.latest_error = str(e.cause)
                raise
            else:
                # Handle other activity errors normally
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
            et_workflow_needs_status_update = update_inputs.status in (
                ExternalDataJob.Status.FAILED,
                ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW,
                ExternalDataJob.Status.BILLING_LIMIT_REACHED,
            )
            if not use_etl_separation or et_workflow_needs_status_update:
                get_data_import_finished_metric(source_type=source_type, status=update_inputs.status.lower()).add(1)

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
