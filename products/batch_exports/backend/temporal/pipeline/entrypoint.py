import datetime as dt

from django.conf import settings
from temporalio import exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.settings.base_variables import TEST
from posthog.temporal.common.logger import get_logger
from products.batch_exports.backend.temporal.batch_exports import (
    BatchExportActivity,
    FinishBatchExportRunInputs,
    finish_batch_export_run,
)
from products.batch_exports.backend.temporal.metrics import (
    get_export_finished_metric,
    get_export_started_metric,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)

LOGGER = get_logger(__name__)


async def execute_batch_export_using_internal_stage(
    activity: BatchExportActivity,
    inputs,
    non_retryable_error_types: list[str],
    interval: str,
    heartbeat_timeout_seconds: int | None = 180,
    maximum_attempts: int = 0,
    initial_retry_interval_seconds: int = 30,
    maximum_retry_interval_seconds: int = 120,
) -> None:
    """
    This is the entrypoint for a new version of the batch export insert activity.

    All batch exports boil down to inserting some data somewhere, and they all follow the same error
    handling patterns, logging and updating run status. For this reason, we have this function
    to abstract executing the main insert activity of each batch export.

    It works in a similar way to the old version of the batch export insert activity, but instead of
    reading data from ClickHouse and exporting it to the destination in batches, we break this down into 2 steps:
        1. Exporting the batch export data directly into our own internal S3 staging area using ClickHouse
        2. Reading the data from the internal S3 staging area and exporting it to the destination using the
            producer/consumer pattern

    Args:
        activity: The 'insert_into_*' activity function to execute.
        inputs: The inputs to the activity.
        non_retryable_error_types: A list of errors to not retry on when executing the activity.
        finish_inputs: Inputs to the 'finish_batch_export_run' to run at the end.
        interval: The interval of the batch export used to set the start to close timeout.
        maximum_attempts: Maximum number of retries for the 'insert_into_*' activity function.
            Assuming the error that triggered the retry is not in non_retryable_error_types.
        initial_retry_interval_seconds: When retrying, seconds until the first retry.
        maximum_retry_interval_seconds: Maximum interval in seconds between retries.
    """
    get_export_started_metric().add(1)

    finish_inputs = FinishBatchExportRunInputs(
        id=inputs.run_id,
        batch_export_id=inputs.batch_export_id,
        status=BatchExportRun.Status.COMPLETED,
        team_id=inputs.team_id,
    )

    if TEST:
        maximum_attempts = 1

    if isinstance(settings.BATCH_EXPORT_HEARTBEAT_TIMEOUT_SECONDS, int):
        heartbeat_timeout_seconds = settings.BATCH_EXPORT_HEARTBEAT_TIMEOUT_SECONDS

    if interval == "hour":
        # TODO - we should reduce this to 1 hour once we are more confident about hitting 1 hour SLAs.
        start_to_close_timeout = dt.timedelta(hours=2)
    elif interval == "day":
        start_to_close_timeout = dt.timedelta(days=1)
    elif interval.startswith("every"):
        _, value, unit = interval.split(" ")
        kwargs = {unit: int(value)}
        # TODO: Consider removing this 20 minute minimum once we are more confident about hitting 5 minute or lower SLAs.
        start_to_close_timeout = max(dt.timedelta(minutes=20), dt.timedelta(**kwargs))
    else:
        raise ValueError(f"Unsupported interval: '{interval}'")

    retry_policy = RetryPolicy(
        initial_interval=dt.timedelta(seconds=initial_retry_interval_seconds),
        maximum_interval=dt.timedelta(seconds=maximum_retry_interval_seconds),
        maximum_attempts=maximum_attempts,
        non_retryable_error_types=non_retryable_error_types,
    )

    try:
        await workflow.execute_activity(
            insert_into_internal_stage_activity,
            BatchExportInsertIntoInternalStageInputs(
                team_id=inputs.team_id,
                batch_export_id=inputs.batch_export_id,
                data_interval_start=inputs.data_interval_start,
                data_interval_end=inputs.data_interval_end,
                exclude_events=inputs.exclude_events,
                include_events=inputs.include_events,
                run_id=inputs.run_id,
                backfill_details=inputs.backfill_details,
                batch_export_model=inputs.batch_export_model,
                batch_export_schema=inputs.batch_export_schema,
                destination_default_fields=inputs.destination_default_fields,
            ),
            start_to_close_timeout=start_to_close_timeout,
            heartbeat_timeout=dt.timedelta(seconds=heartbeat_timeout_seconds) if heartbeat_timeout_seconds else None,
            retry_policy=retry_policy,
        )

        records_completed = await workflow.execute_activity(
            activity,
            inputs,
            start_to_close_timeout=start_to_close_timeout,
            heartbeat_timeout=dt.timedelta(seconds=heartbeat_timeout_seconds) if heartbeat_timeout_seconds else None,
            retry_policy=retry_policy,
        )
        finish_inputs.records_completed = records_completed

    except exceptions.ActivityError as e:
        if isinstance(e.cause, exceptions.CancelledError):
            finish_inputs.status = BatchExportRun.Status.CANCELLED
        elif isinstance(e.cause, exceptions.ApplicationError) and e.cause.type not in non_retryable_error_types:
            finish_inputs.status = BatchExportRun.Status.FAILED_RETRYABLE
        else:
            finish_inputs.status = BatchExportRun.Status.FAILED

        finish_inputs.latest_error = str(e.cause)
        raise

    except Exception:
        finish_inputs.status = BatchExportRun.Status.FAILED
        finish_inputs.latest_error = "An unexpected error has occurred"
        raise

    finally:
        get_export_finished_metric(status=finish_inputs.status.lower()).add(1)

        await workflow.execute_activity(
            finish_batch_export_run,
            finish_inputs,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=0,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )
