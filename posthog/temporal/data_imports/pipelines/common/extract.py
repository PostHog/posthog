from contextlib import contextmanager
from typing import TYPE_CHECKING, NoReturn

from django.conf import settings

import pyarrow as pa
import posthoganalytics
from structlog.typing import FilteringBoundLogger
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client
from posthog.temporal.data_imports.pipelines.pipeline.cdp_producer import CDPProducer
from posthog.temporal.data_imports.util import NonRetryableException

if TYPE_CHECKING:
    from posthog.temporal.data_imports.pipelines.pipeline_sync import PipelineInputs
    from posthog.temporal.data_imports.workflow_activities.import_data_sync import ImportDataActivityInputs

    from products.data_warehouse.backend.models import ExternalDataSource


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


def cdp_producer_clear_chunks(cdp_producer: CDPProducer):
    if cdp_producer.should_produce_table:
        cdp_producer.clear_s3_chunks()


def write_chunk_for_cdp_producer(cdp_producer: CDPProducer, index: int, pa_table: pa.Table):
    if cdp_producer.should_produce_table:
        cdp_producer.write_chunk_for_cdp_producer(chunk=index, table=pa_table)
