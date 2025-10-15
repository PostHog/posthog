import re
import json
import typing
import datetime as dt
import dataclasses

from django.db import close_old_connections

import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy

# TODO: remove dependency
from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.schedule import trigger_schedule_buffer_one
from posthog.temporal.data_imports.metrics import get_data_import_finished_metric
from posthog.temporal.data_imports.row_tracking import finish_row_tracking, get_rows
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
from posthog.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
    import_data_activity_sync,
)
from posthog.temporal.data_imports.workflow_activities.sync_new_schemas import (
    SyncNewSchemasActivityInputs,
    sync_new_schemas_activity,
)
from posthog.temporal.utils import ExternalDataWorkflowInputs
from posthog.utils import get_machine_id
from posthog.warehouse.data_load.source_templates import create_warehouse_templates_for_source
from posthog.warehouse.external_data_source.jobs import update_external_job_status
from posthog.warehouse.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from posthog.warehouse.models.external_data_schema import update_should_sync
from posthog.warehouse.types import ExternalDataSourceType

LOGGER = get_logger(__name__)

Any_Source_Errors: list[str] = [
    "Could not establish session to SSH gateway",
    "Primary key required for incremental syncs",
    "The primary keys for this table are not unique",
    "Integration matching query does not exist",
]

Non_Retryable_Schema_Errors: dict[ExternalDataSourceType, list[str]] = {
    ExternalDataSourceType.BIGQUERY: ["PermissionDenied: 403 request failed", "NotFound: 404"],
    ExternalDataSourceType.STRIPE: [
        "401 Client Error: Unauthorized for url: https://api.stripe.com",
        "403 Client Error: Forbidden for url: https://api.stripe.com",
        "Expired API Key provided",
        "Invalid API Key provided",
        "PermissionError",
    ],
    ExternalDataSourceType.POSTGRES: [
        "NoSuchTableError",
        "is not permitted to log in",
        "Tenant or user not found connection to server",
        "FATAL: Tenant or user not found",
        "error received from server in SCRAM exchange: Wrong password",
        "could not translate host name",
        "timeout expired connection to server at",
        "password authentication failed for user",
        "No primary key defined for table",
        "failed: timeout expired",
        "SSL connection has been closed unexpectedly",
        "Address not in tenant allow_list",
        "FATAL: no such database",
        "does not exist",
        "timestamp too small",
        "QueryTimeoutException",
        "TemporaryFileSizeExceedsLimitException",
        "Name or service not known",
        "Network is unreachable",
        "InsufficientPrivilege",
        "OperationalError: connection failed: connection to server at",
        "password authentication failed connection",
    ],
    ExternalDataSourceType.ZENDESK: [
        "404 Client Error: Not Found for url",
        "403 Client Error: Forbidden for url",
        "401 Client Error",
    ],
    ExternalDataSourceType.MYSQL: [
        "Can't connect to MySQL server on",
        "No primary key defined for table",
        "Access denied for user",
        "sqlstate 42S02",  # Table not found error
        "ProgrammingError: (1146",  # Table not found error
        "OperationalError: (1356",  # View not found error
        "Bad handshake",
    ],
    ExternalDataSourceType.SALESFORCE: [
        "400 Client Error: Bad Request for url",
        "403 Client Error: Forbidden for url",
    ],
    ExternalDataSourceType.SNOWFLAKE: [
        "This account has been marked for decommission",
        "404 Not Found",
        "Your free trial has ended",
        "Your account is suspended due to lack of payment method",
        "MFA authentication is required",
    ],
    ExternalDataSourceType.CHARGEBEE: ["403 Client Error: Forbidden for url", "Unauthorized for url"],
    ExternalDataSourceType.HUBSPOT: ["missing or invalid refresh token", "missing or unknown hub id"],
    ExternalDataSourceType.GOOGLEADS: [
        "PERMISSION_DENIED",
        "UNAUTHENTICATED",
        "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
        "Account has been deleted",
    ],
    ExternalDataSourceType.METAADS: [
        "Failed to refresh token for Meta Ads integration. Please re-authorize the integration."
    ],
    ExternalDataSourceType.MONGODB: ["The DNS query name does not exist", "authentication failed"],
    ExternalDataSourceType.MSSQL: ["Adaptive Server connection failed", "Login failed for user"],
    ExternalDataSourceType.GOOGLESHEETS: [
        "the header row in the worksheet contains duplicates",
        "can't be found",
        "SpreadsheetNotFound",
    ],
    ExternalDataSourceType.LINKEDINADS: ["REVOKED_ACCESS_TOKEN"],
    ExternalDataSourceType.REDDITADS: ["401 Client Error", "404 Client Error"],
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
            f"External data job failed for external data schema {inputs.schema_id} with error: {inputs.internal_error}"
        )

        internal_error_normalized = re.sub("[\n\r\t]", " ", inputs.internal_error)

        source: ExternalDataSource = ExternalDataSource.objects.get(pk=inputs.source_id)
        non_retryable_errors = Non_Retryable_Schema_Errors.get(ExternalDataSourceType(source.source_type))

        if non_retryable_errors is None:
            non_retryable_errors = Any_Source_Errors
        else:
            non_retryable_errors.extend(Any_Source_Errors)

        has_non_retryable_error = any(error in internal_error_normalized for error in non_retryable_errors)
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

    # Produce a more user friendly error message to be displayed in the UI
    latest_error = inputs.latest_error
    try:
        schema = ExternalDataSchema.objects.get(pk=inputs.schema_id)

        latest_error = user_friendly_error_message(
            source_type=source.source_type,
            schema_name=schema.name,
            raw_error=inputs.latest_error or inputs.internal_error,
        )

        logger.exception(latest_error)
    except Exception:
        latest_error = inputs.latest_error

    job = update_external_job_status(
        job_id=job_id,
        status=ExternalDataJob.Status(inputs.status),
        latest_error=latest_error,
        team_id=inputs.team_id,
    )

    job.finished_at = dt.datetime.now(dt.UTC)
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
        try:
            # create external data job and trigger activity
            create_external_data_job_inputs = CreateExternalDataJobModelActivityInputs(
                team_id=inputs.team_id,
                schema_id=inputs.external_data_schema_id,
                source_id=inputs.external_data_source_id,
                billable=inputs.billable,
            )

            job_id, incremental, source_type = await workflow.execute_activity(
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

            job_inputs = ImportDataActivityInputs(
                team_id=inputs.team_id,
                run_id=job_id,
                schema_id=inputs.external_data_schema_id,
                source_id=inputs.external_data_source_id,
                reset_pipeline=inputs.reset_pipeline,
            )

            timeout_params = (
                {"start_to_close_timeout": dt.timedelta(weeks=1), "retry_policy": RetryPolicy(maximum_attempts=9)}
                if incremental
                else {"start_to_close_timeout": dt.timedelta(hours=24), "retry_policy": RetryPolicy(maximum_attempts=3)}
            )

            await workflow.execute_activity(
                import_data_activity_sync,
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

            await workflow.execute_activity(
                calculate_table_size_activity,
                CalculateTableSizeActivityInputs(
                    team_id=inputs.team_id, schema_id=str(inputs.external_data_schema_id), job_id=job_id
                ),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
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


def user_friendly_error_message(source_type: str, schema_name: str, raw_error: str | None) -> str | None:
    """
    Enhance or clarify raw source errors before saving to the job.
    Returns the enhanced error if applicable, otherwise returns the original.
    """

    if not raw_error:
        return raw_error

    error_lower = raw_error.lower()

    if source_type == ExternalDataSourceType.STRIPE:
        if any(keyword in error_lower for keyword in ["permission", "403", "401", "rak_"]):
            table_names = {
                "Dispute": "disputes",
                "Payout": "payouts",
                "CreditNote": "credit notes",
                "Account": "accounts",
            }
            display_name = table_names.get(schema_name, schema_name.lower())
            return f"Your API key does not have permissions to access {display_name}. Please check your API key configuration and permissions in Stripe, then try again."

        if "expired api key" in error_lower:
            return "Your Stripe API key has expired. Please create a new key and reconnect."

    if source_type == ExternalDataSourceType.SALESFORCE and "invalid_session_id" in error_lower:
        return "Your Salesforce session has expired. Please reconnect the source."

    if source_type == ExternalDataSourceType.HUBSPOT and "missing or invalid refresh token" in error_lower:
        return "Your HubSpot connection is invalid or expired. Please reconnect it."

    if source_type == ExternalDataSourceType.SNOWFLAKE:
        if any(keyword in error_lower for keyword in ["account suspended", "trial ended", "decommission"]):
            return "Your Snowflake account has been suspended or trial has ended. Please check your account status."
        if "invalid credentials" in error_lower or "authentication failed" in error_lower:
            return "Snowflake authentication failed. Please check your username, password, and account details."

    if source_type == ExternalDataSourceType.BIGQUERY:
        if "permission denied" in error_lower or "403" in error_lower:
            return "BigQuery permission denied. Please check that your service account has the necessary permissions."
        if "not found" in error_lower:
            return "BigQuery dataset or table not found. Please verify your project, dataset, and table names."

    if source_type == ExternalDataSourceType.ZENDESK:
        if any(keyword in error_lower for keyword in ["401", "403", "unauthorized", "forbidden"]):
            return "Zendesk authentication failed. Please check your API token and subdomain."

    if source_type == ExternalDataSourceType.CHARGEBEE:
        if any(keyword in error_lower for keyword in ["401", "403", "unauthorized", "forbidden"]):
            return "Chargebee authentication failed. Please check your API key and site name."

    if source_type == ExternalDataSourceType.GOOGLESHEETS:
        if "must be real number, not str" in error_lower:
            return "Import failed: all cells in a numerical column must have a value and not be blank"
        if "the header row in the worksheet contains duplicates" in error_lower:
            return "Import failed: There exists duplicate column headers. Please make sure all column headers have values and aren't duplicated."

    return raw_error
