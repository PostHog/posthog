import typing
import datetime as dt
import collections.abc

from django.conf import settings

from temporalio import exceptions, workflow
from temporalio.common import RetryPolicy

from posthog.dataclasses import frozen
from posthog.settings.base_variables import TEST
from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.models.batch_export import BatchExportRun
from products.batch_exports.backend.service import (
    BackfillDetails,
    BatchExportField,
    BatchExportModel,
    BatchExportSchema,
)
from products.batch_exports.backend.temporal.batch_exports import FinishBatchExportRunInputs, finish_batch_export_run
from products.batch_exports.backend.temporal.metrics import get_export_finished_metric, get_export_started_metric
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    InternalStageResult,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.temporal.pipeline.types import BatchExportResult
from products.batch_exports.backend.temporal.workflow_metadata import (
    WorkflowDetails,
    build_logs_link,
    build_team_admin_link,
    humanize_bytes,
)

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
    stage_folder: str | None = None
    on_demand: bool = False
    records_total: int | None = None


class _ComposedBatchExportInputsProtocol(typing.Protocol):
    batch_export: _BatchExportInputsProtocol


# Either the batch export inputs themselves, or an object holding them under `batch_export`.
BatchExportInputs = _BatchExportInputsProtocol | _ComposedBatchExportInputsProtocol

BatchExportResultType = typing.TypeVar("BatchExportResultType", bound=BatchExportResult)
BatchExportInsertActivity = collections.abc.Callable[
    [BatchExportInputs], collections.abc.Awaitable[BatchExportResultType]
]

INITIAL_RETRY_INTERVAL_SECONDS = 1
DEFAULT_MAX_RETRY_INTERVAL_SECONDS = 3600
DEFAULT_MAX_STAGE_RETRY_INTERVAL_SECONDS = 600

STAGE_NON_RETRYABLE_ERROR_TYPES = (
    "InvalidFilterError",
    "DataIntervalEndInFutureError",
    "HogQLQueryResourceLimitExceededError",
)


@frozen
class IntervalConfig:
    # Start-to-close timeouts for the run's two activities: staging the data, then exporting it.
    main_start_to_close: dt.timedelta
    stage_start_to_close: dt.timedelta
    # How many recent runs `finish_batch_export_run` considers when deciding to auto-pause a
    # failing export. A count of runs, not a duration.
    failure_check_window: int


def _get_config_for_interval(interval: str, override_start_to_close: dt.timedelta) -> IntervalConfig:
    """Derive a run's activity timeouts and failure-check window from its interval.

    Raises:
        ValueError: If the interval is not one this function knows how to configure.
    """
    if interval == "hour":
        # TODO - we should reduce this to 1 hour once we are more confident about hitting 1 hour SLAs.
        # TODO: Review timeouts for internal stage activity.
        return IntervalConfig(
            main_start_to_close=max(dt.timedelta(hours=6), override_start_to_close),
            stage_start_to_close=dt.timedelta(hours=1),
            failure_check_window=24,  # A day's worth of runs
        )

    if interval == "day":
        return IntervalConfig(
            main_start_to_close=max(dt.timedelta(days=1), override_start_to_close),
            stage_start_to_close=dt.timedelta(hours=6),
            failure_check_window=7,  # A week's worth of runs
        )

    if interval == "week":
        # TODO - review these once we have more users using weekly batch exports
        return IntervalConfig(
            main_start_to_close=max(dt.timedelta(days=3), override_start_to_close),
            stage_start_to_close=dt.timedelta(days=1),
            failure_check_window=4,  # A (roughly) months' worth of runs
        )

    if interval.startswith("every"):
        _, value, unit = interval.split(" ")
        # TODO: Consider removing this 20 minute minimum once we are more confident about hitting 5 minute or lower SLAs.
        main_start_to_close = max(dt.timedelta(minutes=20), dt.timedelta(**{unit: int(value)}), override_start_to_close)
        if unit == "minutes":
            failure_check_window = 60 // int(value)  # Last hour worth of runs
        else:
            # Anything other than minutes is not currently supported, but just
            # setting a default in case we ever add support for, e.g., seconds.
            failure_check_window = 50
        return IntervalConfig(
            # The stage has to fit inside the main activity for sub-hourly intervals: there is no
            # slack to give it a budget of its own.
            main_start_to_close=main_start_to_close,
            stage_start_to_close=main_start_to_close,
            failure_check_window=failure_check_window,
        )

    raise ValueError(f"Unsupported interval: '{interval}'")


def _get_status_for_activity_error(error: exceptions.ActivityError) -> BatchExportRun.Status:
    """Decide what a failed run's status should be, given the error raised.

    The error could be raised by either the `insert_into_internal_stage_activity` or the
    `insert_into_*_activity_from_stage` activities.
    """
    if isinstance(error.cause, exceptions.CancelledError):
        return BatchExportRun.Status.CANCELLED

    if isinstance(error.cause, exceptions.ApplicationError) and error.cause.type in STAGE_NON_RETRYABLE_ERROR_TYPES:
        return BatchExportRun.Status.FAILED

    # Reaching this outside tests means one of two assumptions broke, so `finish_batch_export_run`
    # logs it. Callers pass `maximum_attempts=0` with no schedule-to-close or run timeout, so a
    # retryable error (or activity timeout) retries forever and never surfaces here; and a terminal
    # error from the destination activity comes back as a `BatchExportResult` with `error_repr`
    # rather than raising. That leaves `TEST`, which forces `maximum_attempts=1`.
    return BatchExportRun.Status.FAILED_RETRYABLE


async def _stage_batch_export_data(
    batch_export_inputs: _BatchExportInputsProtocol,
    *,
    batch_export_id: str,
    is_workflows: bool,
    start_to_close_timeout: dt.timedelta,
    heartbeat_timeout: dt.timedelta | None,
    retry_policy: RetryPolicy,
) -> InternalStageResult:
    """Copy this run's data out of ClickHouse and into our internal S3 staging area.

    `batch_export_id` is passed separately because the staging activity requires it while the
    protocol types it as optional; the caller has already narrowed it.
    """
    stage_inputs = BatchExportInsertIntoInternalStageInputs(
        team_id=batch_export_inputs.team_id,
        batch_export_id=batch_export_id,
        data_interval_start=batch_export_inputs.data_interval_start,
        data_interval_end=batch_export_inputs.data_interval_end,
        exclude_events=batch_export_inputs.exclude_events,
        include_events=batch_export_inputs.include_events,
        run_id=batch_export_inputs.run_id,
        backfill_details=batch_export_inputs.backfill_details,
        batch_export_model=batch_export_inputs.batch_export_model,
        is_workflows=is_workflows,
        batch_export_schema=batch_export_inputs.batch_export_schema,
        destination_default_fields=batch_export_inputs.destination_default_fields,
    )
    return await workflow.execute_activity(
        insert_into_internal_stage_activity,
        stage_inputs,
        start_to_close_timeout=start_to_close_timeout,
        heartbeat_timeout=heartbeat_timeout,
        retry_policy=retry_policy,
    )


async def _finish_run(finish_inputs: FinishBatchExportRunInputs, details: WorkflowDetails, model_name: str) -> None:
    """Record how the run ended: its metric, its workflow details, and its `BatchExportRun` row.

    Runs from a `finally`, so it must cope with every outcome — success, failure, and cancellation —
    and `finish_inputs` carries whichever one happened.
    """
    get_export_finished_metric(status=finish_inputs.status.lower(), model=model_name).add(1)

    bytes_exported = humanize_bytes(finish_inputs.bytes_exported) if finish_inputs.bytes_exported is not None else None
    workflow.set_current_details(
        details.add("Status", finish_inputs.status)
        .add("Records completed", finish_inputs.records_completed)
        .add("Bytes exported", bytes_exported)
        .code_block("Error", finish_inputs.latest_error)
        .render()
    )

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


async def execute_batch_export_using_internal_stage(
    activity: BatchExportInsertActivity[BatchExportResultType],
    inputs: BatchExportInputs,
    interval: str,
    maximum_attempts: int = 0,
    initial_retry_interval_seconds: int = INITIAL_RETRY_INTERVAL_SECONDS,
    maximum_retry_interval_seconds: int = DEFAULT_MAX_RETRY_INTERVAL_SECONDS,
    maximum_stage_retry_interval_seconds: int = DEFAULT_MAX_STAGE_RETRY_INTERVAL_SECONDS,
    override_start_to_close_timeout_seconds: int | None = None,
    is_workflows: bool = False,
) -> BatchExportResultType:
    """Run one batch export: stage its data, write it to the destination, record how it went.

    All batch exports boil down to inserting some data somewhere, and they all follow the same error
    handling patterns, logging and updating run status. For this reason, we have this function
    to abstract executing the main insert activity of each batch export.

    The two steps are:
        1. Copy the run's data from ClickHouse straight into our internal S3 staging area.
        2. Read it back from staging and write it to the destination (producer/consumer).

    Args:
        activity: The 'insert_into_*' activity that writes staged data to this destination.
        inputs: Inputs for that activity — either the batch export inputs themselves, or an object
            holding them under a `batch_export` attribute.
        interval: The export's interval, which sets both activity timeouts and the failure-check
            window. See `_get_config_for_interval`.
        maximum_attempts: Retry limit for both activities, for errors not in their non-retryable
            lists. 0 means unlimited; forced to 1 under TEST.
        initial_retry_interval_seconds: Seconds until the first retry.
        maximum_retry_interval_seconds: Ceiling on the gap between retries of `activity`.
        maximum_stage_retry_interval_seconds: The same ceiling for the staging activity.
        override_start_to_close_timeout_seconds: Raises `activity`'s start-to-close timeout. Only
            ever grants more time: a value below the interval's own timeout is ignored.
        is_workflows: Whether this export reads the workflows model, which is staged by a different
            query.

    Returns:
        The destination activity's result.
    """
    if hasattr(inputs, "batch_export"):
        batch_export_inputs: _BatchExportInputsProtocol = inputs.batch_export  # ty: ignore[invalid-assignment]
    else:
        batch_export_inputs = inputs

    model_name = batch_export_inputs.batch_export_model.name if batch_export_inputs.batch_export_model else "events"
    get_export_started_metric(model=model_name).add(1)

    data_window = f"`{batch_export_inputs.data_interval_start}` → `{batch_export_inputs.data_interval_end}`"
    interval_value = data_window if batch_export_inputs.on_demand else f"{interval} {data_window}"
    details = (
        WorkflowDetails(footer=build_logs_link(workflow.info().workflow_id))
        .add("Team", build_team_admin_link(batch_export_inputs.team_id))
        .add("Interval", interval_value)
        .add("Model", model_name)
    )
    workflow.set_current_details(details.render())

    assert batch_export_inputs.batch_export_id is not None
    assert batch_export_inputs.run_id is not None

    if TEST:
        maximum_attempts = 1

    # Both activities share one heartbeat timeout. Setting it to 0 disables heartbeat timeouts.
    heartbeat_timeout_seconds = settings.BATCH_EXPORT_HEARTBEAT_TIMEOUT_SECONDS
    heartbeat_timeout = dt.timedelta(seconds=heartbeat_timeout_seconds) if heartbeat_timeout_seconds else None

    interval_config = _get_config_for_interval(
        interval, dt.timedelta(seconds=override_start_to_close_timeout_seconds or 0)
    )

    finish_inputs = FinishBatchExportRunInputs(
        id=batch_export_inputs.run_id,
        batch_export_id=batch_export_inputs.batch_export_id,
        status=BatchExportRun.Status.COMPLETED,
        team_id=batch_export_inputs.team_id,
        on_demand=batch_export_inputs.on_demand,
        failure_check_window=interval_config.failure_check_window,
    )

    try:
        stage_result = await _stage_batch_export_data(
            batch_export_inputs,
            batch_export_id=batch_export_inputs.batch_export_id,
            is_workflows=is_workflows,
            start_to_close_timeout=interval_config.stage_start_to_close,
            heartbeat_timeout=heartbeat_timeout,
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=initial_retry_interval_seconds),
                maximum_interval=dt.timedelta(seconds=maximum_stage_retry_interval_seconds),
                maximum_attempts=maximum_attempts,
                non_retryable_error_types=list(STAGE_NON_RETRYABLE_ERROR_TYPES),
            ),
        )

        batch_export_inputs.stage_folder = stage_result.stage_folder
        batch_export_inputs.records_total = stage_result.records_total
        if stage_result.records_total is not None:
            workflow.set_current_details(details.add("Staged records", stage_result.records_total).render())

        result = await workflow.execute_activity(
            activity,
            inputs,
            start_to_close_timeout=interval_config.main_start_to_close,
            heartbeat_timeout=heartbeat_timeout,
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=initial_retry_interval_seconds),
                maximum_interval=dt.timedelta(seconds=maximum_retry_interval_seconds),
                maximum_attempts=maximum_attempts,
            ),
        )
        finish_inputs.records_completed = result.records_completed
        finish_inputs.bytes_exported = result.bytes_exported
        finish_inputs.records_failed = result.records_failed
        if result.error_repr:
            finish_inputs.latest_error = result.error_repr
            finish_inputs.status = BatchExportRun.Status.FAILED

    except exceptions.ActivityError as e:
        finish_inputs.status = _get_status_for_activity_error(e)
        finish_inputs.latest_error = str(e.cause)
        raise

    except Exception:
        finish_inputs.status = BatchExportRun.Status.FAILED
        finish_inputs.latest_error = "An unexpected error has occurred"
        raise

    finally:
        await _finish_run(finish_inputs, details, model_name)

    return result
