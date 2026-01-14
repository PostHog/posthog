import gc
from collections.abc import Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, NoReturn

from django.conf import settings

import pyarrow as pa
import posthoganalytics
from structlog.typing import FilteringBoundLogger
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client
from posthog.temporal.data_imports.pipelines.common.load import get_incremental_field_value
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    BillingLimitsWillBeReachedException,
    DuplicatePrimaryKeysException,
)
from posthog.temporal.data_imports.row_tracking import decrement_rows, increment_rows, will_hit_billing_limit
from posthog.temporal.data_imports.util import NonRetryableException

if TYPE_CHECKING:
    from posthog.temporal.data_imports.pipelines.pipeline_sync import PipelineInputs
    from posthog.temporal.data_imports.workflow_activities.import_data_sync import ImportDataActivityInputs

    from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource


@contextmanager
def get_redis_client():
    redis_client = None
    try:
        if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
            raise Exception(
                "Missing env vars for dwh row tracking: DATA_WAREHOUSE_REDIS_HOST or DATA_WAREHOUSE_REDIS_PORT"
            )

        redis_client = get_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
        redis_client.ping()
    except Exception as e:
        capture_exception(e)

    try:
        yield redis_client
    finally:
        pass


def build_non_retryable_errors_redis_key(team_id: int, source_id: str, run_id: str) -> str:
    return f"posthog:data_warehouse:non_retryable_errors:{team_id}:{source_id}:{run_id}"


def trim_source_job_inputs(source: "ExternalDataSource") -> None:
    if not source.job_inputs:
        return

    did_update_inputs = False
    for key, value in source.job_inputs.items():
        if isinstance(value, str):
            if value.startswith(" ") or value.endswith(" "):
                source.job_inputs[key] = value.strip()
                did_update_inputs = True

    if did_update_inputs:
        source.save()


def report_heartbeat_timeout(inputs: "ImportDataActivityInputs", logger: FilteringBoundLogger) -> None:
    logger.debug("Checking for heartbeat timeout reporting...")

    try:
        info = activity.info()
        heartbeat_timeout = info.heartbeat_timeout
        current_attempt_scheduled_time = info.current_attempt_scheduled_time

        if not heartbeat_timeout:
            logger.debug(f"No heartbeat timeout set for this activity: {heartbeat_timeout}")
            return

        if not current_attempt_scheduled_time:
            logger.debug(f"No current attempt scheduled time set for this activity: {current_attempt_scheduled_time}")
            return

        if info.attempt < 2:
            logger.debug("First attempt of activity, no heartbeat timeout to report.")
            return

        heartbeat_details = info.heartbeat_details
        if not isinstance(heartbeat_details, tuple | list) or len(heartbeat_details) < 1:
            logger.debug(
                f"No heartbeat details found to analyze for timeout: {heartbeat_details}. Class: {heartbeat_details.__class__.__name__}"
            )
            return

        last_heartbeat = heartbeat_details[-1]
        logger.debug(f"Resuming activity after failure. Last heartbeat details: {last_heartbeat}")

        if not isinstance(last_heartbeat, dict):
            logger.debug(
                f"Last heartbeat details not in expected format (dict). Found: {type(last_heartbeat)}: {last_heartbeat}"
            )
            return

        last_heartbeat_host = last_heartbeat.get("host", None)
        last_heartbeat_timestamp = last_heartbeat.get("ts", None)

        logger.debug(f"Last heartbeat was {last_heartbeat}")

        if last_heartbeat_host is None or last_heartbeat_timestamp is None:
            logger.debug("Incomplete heartbeat details. No host or timestamp found.")
            return

        try:
            last_heartbeat_timestamp = float(last_heartbeat_timestamp)
        except (TypeError, ValueError):
            logger.debug(f"Last heartbeat timestamp could not be converted to float: {last_heartbeat_timestamp}")
            return

        gap_between_beats = current_attempt_scheduled_time.timestamp() - float(last_heartbeat_timestamp)
        if gap_between_beats > heartbeat_timeout.total_seconds():
            logger.debug(
                "Last heartbeat was longer ago than the heartbeat timeout allows. Likely due to a pod OOM or restart.",
                last_heartbeat_host=last_heartbeat_host,
                last_heartbeat_timestamp=last_heartbeat_timestamp,
                gap_between_beats=gap_between_beats,
                heartbeat_timeout_seconds=heartbeat_timeout.total_seconds(),
            )

            posthoganalytics.capture(
                "dwh_pod_heartbeat_timeout",
                distinct_id=None,
                properties={
                    "team_id": inputs.team_id,
                    "schema_id": str(inputs.schema_id),
                    "source_id": str(inputs.source_id),
                    "run_id": inputs.run_id,
                    "host": last_heartbeat_host,
                    "gap_between_beats": gap_between_beats,
                    "heartbeat_timeout_seconds": heartbeat_timeout.total_seconds(),
                    "task_queue": info.task_queue,
                    "workflow_id": info.workflow_id,
                    "workflow_run_id": info.workflow_run_id,
                    "workflow_type": info.workflow_type,
                    "attempt": info.attempt,
                },
            )
        else:
            logger.debug("Last heartbeat was within the heartbeat timeout window. No action needed.")
    except Exception as e:
        logger.debug(f"Error while reporting heartbeat timeout: {e}", exc_info=e)


def handle_non_retryable_error(
    job_inputs: "PipelineInputs",
    error_msg: str,
    logger: FilteringBoundLogger,
    error: Exception,
) -> NoReturn:
    with get_redis_client() as redis_client:
        if redis_client is None:
            logger.debug(f"Failed to get Redis client for non-retryable error tracking. error={error_msg}")
            raise NonRetryableException() from error

        retry_key = build_non_retryable_errors_redis_key(
            job_inputs.team_id, str(job_inputs.source_id), job_inputs.run_id
        )
        attempts = redis_client.incr(retry_key)

        if attempts <= 3:
            redis_client.expire(retry_key, 86400)  # Expire after 24 hours
            logger.debug(f"Non-retryable error attempt {attempts}/3, retrying. error={error_msg}")
            raise error

    logger.debug(f"Non-retryable error after {attempts} runs, giving up. error={error_msg}")
    raise NonRetryableException() from error


def reset_rows_synced_if_needed(
    job: "ExternalDataJob",
    is_incremental: bool,
    reset_pipeline: bool,
    should_resume: bool,
) -> None:
    # Reset the rows_synced count - this may not be 0 if the job restarted due to a heartbeat timeout
    if (
        job.rows_synced is not None
        and job.rows_synced != 0
        and (not is_incremental or reset_pipeline is True)
        and not should_resume
    ):
        job.rows_synced = 0
        job.save()


def validate_incremental_sync(
    is_incremental: bool,
    resource: SourceResponse,
) -> None:
    # Check for duplicate primary keys
    if is_incremental and resource.has_duplicate_primary_keys:
        raise DuplicatePrimaryKeysException(
            f"The primary keys for this table are not unique. We can't sync incrementally until the table "
            f"has a unique primary key. Primary keys being used are: {resource.primary_keys}"
        )


def setup_row_tracking_with_billing_check(
    team_id: int,
    schema: "ExternalDataSchema",
    resource: SourceResponse,
    logger: FilteringBoundLogger,
) -> None:
    if resource.rows_to_sync:
        increment_rows(team_id, schema.id, resource.rows_to_sync)
        # Check billing limits against incoming rows
        if will_hit_billing_limit(team_id=team_id, source=schema.source, logger=logger):
            raise BillingLimitsWillBeReachedException(
                f"Your account will hit your Data Warehouse billing limits syncing {resource.name} "
                f"with {resource.rows_to_sync} rows"
            )


def handle_reset_or_full_refresh(
    reset_pipeline: bool,
    should_resume: bool,
    schema: "ExternalDataSchema",
    reset_callback: Callable[[], None],
    logger: FilteringBoundLogger,
    log_prefix: str = "",
) -> None:
    from products.data_warehouse.backend.models import ExternalDataSchema as ExternalDataSchemaModel

    if reset_pipeline and not should_resume:
        logger.debug(f"{log_prefix}Cleaning up previous data due to reset_pipeline")
        reset_callback()
        schema.update_sync_type_config_for_reset_pipeline()
    elif schema.sync_type == ExternalDataSchemaModel.SyncType.FULL_REFRESH and not should_resume:
        # Avoid schema mismatches from existing data about to be overwritten
        logger.debug(f"{log_prefix}Cleaning up previous data due to full refresh sync")
        reset_callback()
        schema.update_sync_type_config_for_reset_pipeline()


def cleanup_memory(pa_memory_pool: pa.MemoryPool, py_table: pa.Table | None = None) -> None:
    if py_table is not None:
        del py_table
    pa_memory_pool.release_unused()
    gc.collect()


def update_incremental_field_values(
    schema: "ExternalDataSchema",
    pa_table: pa.Table,
    resource: SourceResponse,
    last_incremental_field_value: Any,
    earliest_incremental_field_value: Any,
    logger: FilteringBoundLogger,
    log_prefix: str = "",
) -> tuple[Any, Any]:
    # Update the incremental_field_last_value.
    # If the resource returns data sorted in ascending timestamp order, we can update the
    # `incremental_field_last_value` in the schema.
    # However, if the data is returned in descending order, we only want to update the
    # `incremental_field_last_value` once we have processed all of the data, otherwise if we fail halfway through,
    # we'd not process older data the next time we retry. But we do store the earliest available value so that we
    # can resume syncs if they stop mid way through without having to start from the beginning
    last_value = get_incremental_field_value(schema, pa_table)

    if last_value is not None:
        if (last_incremental_field_value is None) or (last_value > last_incremental_field_value):
            last_incremental_field_value = last_value

        if resource.sort_mode == "asc":
            logger.debug(f"{log_prefix}Updating incremental_field_last_value with {last_incremental_field_value}")
            schema.update_incremental_field_value(last_incremental_field_value)

        if resource.sort_mode == "desc":
            earliest_value = get_incremental_field_value(schema, pa_table, aggregate="min")

            if earliest_incremental_field_value is None or earliest_value < earliest_incremental_field_value:
                earliest_incremental_field_value = earliest_value
                logger.debug(f"{log_prefix}Updating incremental_field_earliest_value with {earliest_value}")
                schema.update_incremental_field_value(earliest_value, type="earliest")

    return last_incremental_field_value, earliest_incremental_field_value


def update_row_tracking_after_batch(
    job_id: str,
    team_id: int,
    schema_id: Any,
    row_count: int,
    logger: FilteringBoundLogger,
) -> None:
    from posthog.temporal.data_imports.pipelines.common.load import update_job_row_count

    update_job_row_count(job_id, row_count, logger)
    decrement_rows(team_id, schema_id, row_count)


def should_check_shutdown(
    schema: "ExternalDataSchema",
    resource: SourceResponse,
    reset_pipeline: bool,
    source_is_resumable: bool,
) -> bool:
    # Only raise if we're not running in descending order, otherwise we'll often not
    # complete the job before the incremental value can be updated. Or if the source is
    # resumable
    # TODO: raise when we're within `x` time of the worker being forced to shutdown
    # Raising during a full reset will reset our progress back to 0 rows
    incremental_sync_raise_during_shutdown = (
        schema.should_use_incremental_field and resource.sort_mode != "desc" and not reset_pipeline
    )
    return incremental_sync_raise_during_shutdown or source_is_resumable


def finalize_desc_sort_incremental_value(
    resource: SourceResponse,
    schema: "ExternalDataSchema",
    last_incremental_field_value: Any,
    logger: FilteringBoundLogger,
    log_prefix: str = "",
) -> None:
    # As mentioned above, for sort mode 'desc' we only want to update the `incremental_field_last_value` once we
    # have processed all of the data (we could also update it here for 'asc' but it's not needed)
    if resource.sort_mode == "desc" and last_incremental_field_value is not None:
        logger.debug(
            f"{log_prefix}Sort mode is 'desc' -> updating incremental_field_last_value "
            f"with {last_incremental_field_value}"
        )
        schema.refresh_from_db()
        schema.update_incremental_field_value(last_incremental_field_value)
