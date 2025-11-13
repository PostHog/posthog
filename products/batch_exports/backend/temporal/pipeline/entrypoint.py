import typing
import datetime as dt
import collections.abc

from django.conf import settings

from temporalio import exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import BackfillDetails, BatchExportField, BatchExportModel, BatchExportSchema
from posthog.settings.base_variables import TEST
from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.temporal.batch_exports import FinishBatchExportRunInputs, finish_batch_export_run
from products.batch_exports.backend.temporal.metrics import get_export_finished_metric, get_export_started_metric
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult

LOGGER = get_write_only_logger(__name__)


class _BatchExportInputsProtocol(typing.Protocol):
    team_id: int
    data_interval_start: str | None
    data_interval_end: str
    exclude_events: list[str] | None = None
    include_events: list[str] | None = None
    run_id: str | None = None
    backfill_details: BackfillDetails | None = None
    batch_export_model: BatchExportModel | None = None
    batch_export_schema: BatchExportSchema | None = None
    is_backfill: bool = False
    batch_export_id: str | None = None
    destination_default_fields: list[BatchExportField] | None = None


class _ComposedBatchExportInputsProtocol(typing.Protocol):
    batch_export: _BatchExportInputsProtocol


InputsType = typing.TypeVar("InputsType", bound=_BatchExportInputsProtocol)
ComposedInputsType = typing.TypeVar("ComposedInputsType", bound=_ComposedBatchExportInputsProtocol)

BatchExportInsertActivity = collections.abc.Callable[
    [InputsType | ComposedInputsType], collections.abc.Awaitable[BatchExportResult]
]


async def execute_batch_export_using_internal_stage(
    activity: BatchExportInsertActivity,
    inputs: InputsType | ComposedInputsType,
    interval: str,
    heartbeat_timeout_seconds: int | None = 180,
    maximum_attempts: int = 0,
    initial_retry_interval_seconds: int = 5,
    maximum_retry_interval_seconds: int = 120,
    override_start_to_close_timeout_seconds: int | None = None,
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
        interval: The interval of the batch export used to set the start to close timeout.
        maximum_attempts: Maximum number of retries for the 'insert_into_*' activity function.
            Assuming the error that triggered the retry is not in non_retryable_error_types.
        initial_retry_interval_seconds: When retrying, seconds until the first retry.
        maximum_retry_interval_seconds: Maximum interval in seconds between retries.
        override_start_to_close_timeout_seconds: Optionally, override the start-to-close
            timeout of the main activity. If this is lower than the calculated default
            timeout for the main activity, then the default will be preferred.
    """
    get_export_started_metric().add(1)

    if hasattr(inputs, "batch_export"):
        batch_export_inputs: _BatchExportInputsProtocol = inputs.batch_export
    else:
        batch_export_inputs = inputs

    assert batch_export_inputs.batch_export_id is not None
    assert batch_export_inputs.run_id is not None

    finish_inputs = FinishBatchExportRunInputs(
        id=batch_export_inputs.run_id,
        batch_export_id=batch_export_inputs.batch_export_id,
        status=BatchExportRun.Status.COMPLETED,
        team_id=batch_export_inputs.team_id,
    )

    if TEST:
        maximum_attempts = 1

    if isinstance(settings.BATCH_EXPORT_HEARTBEAT_TIMEOUT_SECONDS, int):
        heartbeat_timeout_seconds = settings.BATCH_EXPORT_HEARTBEAT_TIMEOUT_SECONDS

    override_start_to_close_timeout_timedelta = dt.timedelta(seconds=override_start_to_close_timeout_seconds or 0)
    if interval == "hour":
        # TODO - we should reduce this to 1 hour once we are more confident about hitting 1 hour SLAs.
        # TODO: Review timeouts for internal stage activity.
        main_activity_start_to_close_timeout = max(dt.timedelta(hours=2), override_start_to_close_timeout_timedelta)
        stage_activity_start_to_close_timeout = dt.timedelta(hours=1)
    elif interval == "day":
        main_activity_start_to_close_timeout = max(dt.timedelta(days=1), override_start_to_close_timeout_timedelta)
        stage_activity_start_to_close_timeout = main_activity_start_to_close_timeout
    elif interval.startswith("every"):
        _, value, unit = interval.split(" ")
        kwargs = {unit: int(value)}
        # TODO: Consider removing this 20 minute minimum once we are more confident about hitting 5 minute or lower SLAs.
        main_activity_start_to_close_timeout = max(
            dt.timedelta(minutes=20), dt.timedelta(**kwargs), override_start_to_close_timeout_timedelta
        )
        stage_activity_start_to_close_timeout = main_activity_start_to_close_timeout
    else:
        raise ValueError(f"Unsupported interval: '{interval}'")

    try:
        await workflow.execute_activity(
            insert_into_internal_stage_activity,
            BatchExportInsertIntoInternalStageInputs(
                team_id=batch_export_inputs.team_id,
                batch_export_id=batch_export_inputs.batch_export_id,
                data_interval_start=batch_export_inputs.data_interval_start,
                data_interval_end=batch_export_inputs.data_interval_end,
                exclude_events=batch_export_inputs.exclude_events,
                include_events=batch_export_inputs.include_events,
                run_id=batch_export_inputs.run_id,
                backfill_details=batch_export_inputs.backfill_details,
                batch_export_model=batch_export_inputs.batch_export_model,
                batch_export_schema=batch_export_inputs.batch_export_schema,
                destination_default_fields=batch_export_inputs.destination_default_fields,
            ),
            start_to_close_timeout=stage_activity_start_to_close_timeout,
            heartbeat_timeout=dt.timedelta(seconds=heartbeat_timeout_seconds) if heartbeat_timeout_seconds else None,
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=initial_retry_interval_seconds),
                maximum_interval=dt.timedelta(seconds=maximum_retry_interval_seconds),
                maximum_attempts=maximum_attempts,
            ),
        )

        result = await workflow.execute_activity(
            activity,
            inputs,
            start_to_close_timeout=main_activity_start_to_close_timeout,
            heartbeat_timeout=dt.timedelta(seconds=heartbeat_timeout_seconds) if heartbeat_timeout_seconds else None,
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=initial_retry_interval_seconds),
                maximum_interval=dt.timedelta(seconds=maximum_retry_interval_seconds),
                maximum_attempts=maximum_attempts,
            ),
        )
        finish_inputs.records_completed = result.records_completed
        finish_inputs.bytes_exported = result.bytes_exported
        if result.error_repr:
            finish_inputs.latest_error = result.error_repr
            finish_inputs.status = BatchExportRun.Status.FAILED

    except exceptions.ActivityError as e:
        if isinstance(e.cause, exceptions.CancelledError):
            finish_inputs.status = BatchExportRun.Status.CANCELLED
        else:
            finish_inputs.status = BatchExportRun.Status.FAILED_RETRYABLE

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
