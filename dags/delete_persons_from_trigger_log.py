"""Dagster job for deleting posthog_person_new rows (cascading to N associated posthog_persondistinctid rows)
that are present in the trigger log table used to capture deletes on the unpartitioned DB while we
transitioned to the new, partitioned DB."""

import time
from typing import Any

import dagster
import psycopg2
import psycopg2.errors
from dagster_k8s import k8s_job_executor

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.custom_metrics import MetricsClient

from dags.common import JobOwners

MAX_RETRY_ATTEMPTS = 5


class DeletePersonsFromTriggerLogConfig(dagster.Config):
    """Configuration for the delete persons from trigger log job."""

    persons_table: str = "posthog_person_new"
    chunk_size: int = 10_000  # ID range per chunk
    batch_size: int = 100  # Work in small batches since each person ID will cascade a delete to many distinct ID rows
    max_id: int | None = None  # Optional override for max ID to resume from partial state
    min_id: int | None = None  # Optional override for min ID to resume from partial state


@dagster.op
def get_id_range_for_dpft(
    context: dagster.OpExecutionContext,
    config: DeletePersonsFromTriggerLogConfig,
    database: dagster.ResourceParam[psycopg2.extensions.connection],
) -> tuple[int, int]:
    """
    Query source database for MIN(id) and MAX(id) from posthog_person_deletes_log
    table. If min_id and max_id are provided in config, uses that instead of querying.
    Returns tuple (min_id, max_id).
    """
    with database.cursor() as cursor:
        # Use config min_id if provided, otherwise query database
        if config.min_id is not None:
            min_id = config.min_id
            context.log.info(f"Using configured min_id override: {min_id}")
        else:
            min_query = f"SELECT MIN(id) as min_id FROM posthog_person_deletes_log"
            context.log.info(f"Querying min ID: {min_query}")
            cursor.execute(min_query)
            min_result = cursor.fetchone()

            if min_result is None or min_result["min_id"] is None:
                context.log.exception("Source table has no valid min ID")
                # Note: No metrics client here as this is get_id_range op, not copy_chunk
                raise dagster.Failure("Source table has no valid min ID")

            min_id = int(min_result["min_id"])

        # Use config max_id if provided, otherwise query database
        if config.max_id is not None:
            max_id = config.max_id
            context.log.info(f"Using configured max_id override: {max_id}")
        else:
            max_query = f"SELECT MAX(id) as max_id FROM posthog_person_deletes_log"
            context.log.info(f"Querying max ID: {max_query}")
            cursor.execute(max_query)
            max_result = cursor.fetchone()

            if max_result is None or max_result["max_id"] is None:
                context.log.exception(f"{config.persons_table} table has no valid max ID")
                # Note: No metrics client here as this is get_id_range op, not copy_chunk
                raise dagster.Failure(f"{config.persons_table} table has no valid max ID")

            max_id = int(max_result["max_id"])

        # Validate that max_id >= min_id
        if max_id < min_id:
            error_msg = f"Invalid ID range: max_id ({max_id}) < min_id ({min_id})"
            context.log.error(error_msg)
            # Note: No metrics client here as this is get_id_range op, not copy_chunk
            raise dagster.Failure(error_msg)

        context.log.info(f"ID range: min={min_id}, max={max_id}, total_ids={max_id - min_id + 1}")
        context.add_output_metadata(
            {
                "min_id": dagster.MetadataValue.int(min_id),
                "min_id_source": dagster.MetadataValue.text("config" if config.min_id is not None else "database"),
                "max_id": dagster.MetadataValue.int(max_id),
                "max_id_source": dagster.MetadataValue.text("config" if config.max_id is not None else "database"),
                "total_ids": dagster.MetadataValue.int(max_id - min_id + 1),
            }
        )

        return (min_id, max_id)


@dagster.op(out=dagster.DynamicOut(tuple[int, int]))
def create_chunks_for_dpft(
    context: dagster.OpExecutionContext,
    config: DeletePersonsFromTriggerLogConfig,
    id_range: tuple[int, int],
):
    """
    Divide ID space into chunks of chunk_size.
    Yields DynamicOutput for each chunk in reverse order (highest IDs first, lowest IDs last).
    This ensures that if the job fails partway through, the final chunk to process will be
    the one starting at the source table's min_id.
    """
    min_id, max_id = id_range
    chunk_size = config.chunk_size

    # First, collect all chunks
    chunks = []
    chunk_min = min_id
    chunk_num = 0

    while chunk_min <= max_id:
        chunk_max = min(chunk_min + chunk_size - 1, max_id)
        chunks.append((chunk_min, chunk_max, chunk_num))
        chunk_min = chunk_max + 1
        chunk_num += 1

    context.log.info(f"Created {chunk_num} chunks total")

    # Yield chunks in reverse order (highest IDs first)
    for chunk_min, chunk_max, chunk_num in reversed(chunks):
        chunk_key = f"chunk_{chunk_min}_{chunk_max}"
        context.log.info(f"Yielding chunk {chunk_num}: {chunk_min} to {chunk_max}")
        yield dagster.DynamicOutput(
            value=(chunk_min, chunk_max),
            mapping_key=chunk_key,
        )


@dagster.op
def scan_delete_chunk_for_dpft(
    context: dagster.OpExecutionContext,
    config: DeletePersonsFromTriggerLogConfig,
    chunk: tuple[int, int],
    database: dagster.ResourceParam[psycopg2.extensions.connection],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dict[str, Any]:
    """
    Scan posthog_person_deletes_log table for records that have an associated posthog_person_new row,
    and deletes the corresponding posthog_person_new row. Processes in batches of batch_size person IDs,
    and deletes the corresponding posthog_person_new rows in batches of delete_batch_size person IDs.
    """
    chunk_min, chunk_max = chunk
    batch_size = config.batch_size
    chunk_id = f"chunk_{chunk_min}_{chunk_max}"
    job_name = context.run.job_name

    # Initialize metrics client
    metrics_client = MetricsClient(cluster)

    context.log.info(f"Starting chunk scan and delete for ID range: {chunk_min} to {chunk_max}")

    total_records_deleted = 0
    batch_start_id = chunk_min
    failed_batch_start_id: int | None = None

    try:
        with database.cursor() as cursor:
            # Set session-level settings once for the entire chunk
            cursor.execute("SET application_name = 'delete_persons_from_trigger_log'")
            cursor.execute("SET lock_timeout = '5s'")
            cursor.execute("SET statement_timeout = '30min'")
            cursor.execute("SET maintenance_work_mem = '12GB'")
            cursor.execute("SET work_mem = '512MB'")
            cursor.execute("SET temp_buffers = '512MB'")
            cursor.execute("SET max_parallel_workers_per_gather = 2")
            cursor.execute("SET max_parallel_maintenance_workers = 2")
            cursor.execute("SET synchronous_commit = off")

            retry_attempt = 0
            while batch_start_id <= chunk_max:
                try:
                    # Track batch start time for duration metric
                    batch_start_time = time.time()

                    # Calculate batch end ID
                    batch_end_id = min(batch_start_id + batch_size, chunk_max)

                    # Track records attempted - this is also our exit condition
                    records_scanned = batch_end_id - batch_start_id
                    if records_scanned <= 0:
                        break

                    # Begin transaction (settings already applied at session level)
                    cursor.execute("BEGIN")

                    # Query to find posthog_person_deletes_log rows
                    scan_query = f"""
SELECT pdl.id, pdl.team_id
FROM posthog_person_deletes_log AS pdl
WHERE pdl.id >= %s AND pdl.id <= %s
  AND EXISTS (
    SELECT 1
    FROM {config.persons_table} AS p
    WHERE pdl.id = p.id
      AND pdl.team_id = p.team_id
  )
ORDER BY pdl.id
"""
                    cursor.execute(scan_query, (batch_start_id, batch_end_id))
                    rows = cursor.fetchall()
                    ids_to_delete = set[tuple[int, int]]({(int(row["team_id"]), int(row["id"])) for row in rows})

                    # Commit the transaction
                    cursor.execute("COMMIT")

                    records_deleted = 0
                    for team_id, person_id in ids_to_delete:
                        try:
                            context.log.info(
                                f"Deleting person={person_id}, team_id={team_id} from {config.persons_table} (attempt {retry_attempt + 1})"
                            )
                            cursor.execute("BEGIN")
                            cursor.execute(
                                f"DELETE FROM {config.persons_table} WHERE team_id = %s AND id = %s",
                                (team_id, person_id),
                            )
                            records_deleted += cursor.rowcount
                            cursor.execute("COMMIT")
                        except Exception as delete_error:
                            # bubble up errors to be retried on deadlock etc. or fail the job
                            context.log.exception(
                                f"Failed to delete person={person_id}, team_id={team_id} from {config.persons_table} (attempt {retry_attempt + 1}): {delete_error}"
                            )
                            raise

                    try:
                        metrics_client.increment(
                            "delete_persons_from_trigger_log_records_deleted_total",
                            labels={"job_name": job_name, "chunk_id": chunk_id},
                            value=float(records_deleted),
                        ).result()
                    except Exception:
                        pass  # Don't fail on metrics error

                    try:
                        metrics_client.increment(
                            "delete_persons_from_trigger_log_batches_scanned_total",
                            labels={"job_name": job_name, "chunk_id": chunk_id},
                            value=records_scanned,
                        ).result()
                    except Exception:
                        pass

                    # Track batch duration metric (IV)
                    batch_duration_seconds = time.time() - batch_start_time
                    try:
                        metrics_client.increment(
                            "delete_persons_from_trigger_log_batch_duration_seconds_total",
                            labels={"job_name": job_name, "chunk_id": chunk_id},
                            value=batch_duration_seconds,
                        ).result()
                    except Exception:
                        pass

                    total_records_deleted += records_deleted

                    context.log.info(
                        f"Deleted batch: {records_deleted} of {records_scanned} records "
                        f"(chunk {chunk_min}-{chunk_max}, batch ID range {batch_start_id} to {batch_end_id})"
                    )

                    # Update batch_start_id for next iteration
                    batch_start_id = batch_end_id + 1
                    retry_attempt = 0

                except Exception as batch_error:
                    # Rollback transaction on error
                    try:
                        cursor.execute("ROLLBACK")
                    except Exception as rollback_error:
                        context.log.exception(
                            f"Failed to rollback transaction for batch starting at ID {batch_start_id}"
                            f"in chunk {chunk_min}-{chunk_max}: {str(rollback_error)}"
                        )
                        pass  # Ignore rollback errors

                    # Check if error is a serialization failure, pause and retry if so
                    serialization_failure_class = getattr(psycopg2.errors, "SerializationFailure", None)
                    is_serialization_failure = (
                        serialization_failure_class is not None and isinstance(batch_error, serialization_failure_class)
                    ) or (isinstance(batch_error, psycopg2.Error) and getattr(batch_error, "pgcode", None) == "40001")
                    if is_serialization_failure:
                        error_msg = (
                            f"Serialization failure detected for batch starting at ID {batch_start_id} "
                            f"in chunk {chunk_min}-{chunk_max}. Error is: {batch_error}. "
                            "This is expected due to concurrent transactions. "
                        )
                        context.log.warning(error_msg)
                        if retry_attempt < MAX_RETRY_ATTEMPTS:
                            retry_attempt += 1
                            context.log.warning(f"Retrying batch {retry_attempt} of {MAX_RETRY_ATTEMPTS}...")
                            time.sleep(1)
                            continue

                    # Check if error is a deadlock, pause and retry if so
                    deadlock_detected_class = getattr(psycopg2.errors, "DeadlockDetected", None)
                    is_deadlock = (
                        deadlock_detected_class is not None and isinstance(batch_error, deadlock_detected_class)
                    ) or (isinstance(batch_error, psycopg2.Error) and getattr(batch_error, "pgcode", None) == "40P01")
                    if is_deadlock:
                        error_msg = (
                            f"Deadlock detected for batch starting at ID {batch_start_id} "
                            f"in chunk {chunk_min}-{chunk_max}. Error is: {batch_error}. "
                            "This is expected due to concurrent transactions. "
                        )
                        context.log.warning(error_msg)
                        if retry_attempt < MAX_RETRY_ATTEMPTS:
                            retry_attempt += 1
                            context.log.warning(f"Retrying batch {retry_attempt} of {MAX_RETRY_ATTEMPTS}...")
                            time.sleep(1)
                            continue

                    # Handle unexpected errors by bubbling up to dagster.Failure
                    failed_batch_start_id = batch_start_id
                    error_msg = (
                        f"Failed to scan and delete rows in batch starting at ID {batch_start_id} "
                        f"in chunk {chunk_min}-{chunk_max}: {str(batch_error)}"
                    )
                    context.log.exception(error_msg)
                    # Report fatal error metric before raising
                    try:
                        metrics_client.increment(
                            "delete_persons_from_trigger_log_error",
                            labels={"job_name": job_name, "chunk_id": chunk_id, "reason": "batch_scan_delete_failed"},
                            value=1.0,
                        ).result()
                    except Exception:
                        pass  # Don't fail on metrics error

                    raise dagster.Failure(
                        description=error_msg,
                        metadata={
                            "chunk_min_id": dagster.MetadataValue.int(chunk_min),
                            "chunk_max_id": dagster.MetadataValue.int(chunk_max),
                            "failed_batch_start_id": dagster.MetadataValue.int(failed_batch_start_id)
                            if failed_batch_start_id
                            else dagster.MetadataValue.text("N/A"),
                            "error_message": dagster.MetadataValue.text(str(batch_error)),
                            "records_deleted_before_failure": dagster.MetadataValue.int(total_records_deleted),
                        },
                    ) from batch_error

    except dagster.Failure:
        # Re-raise Dagster failures as-is (they already have metadata and metrics)
        raise
    except Exception as e:
        # Catch any other unexpected errors
        error_msg = f"Unexpected error scanning and deleting from chunk {chunk_min}-{chunk_max}: {str(e)}"
        context.log.exception(error_msg)
        # Report fatal error metric before raising
        try:
            metrics_client.increment(
                "delete_persons_from_trigger_log_error",
                labels={"job_name": job_name, "chunk_id": chunk_id, "reason": "unexpected_scan_delete_error"},
                value=1.0,
            ).result()
        except Exception:
            pass  # Don't fail on metrics error
        raise dagster.Failure(
            description=error_msg,
            metadata={
                "chunk_min_id": dagster.MetadataValue.int(chunk_min),
                "chunk_max_id": dagster.MetadataValue.int(chunk_max),
                "failed_batch_start_id": dagster.MetadataValue.int(failed_batch_start_id)
                if failed_batch_start_id
                else dagster.MetadataValue.int(batch_start_id),
                "error_message": dagster.MetadataValue.text(str(e)),
                "records_deleted_before_failure": dagster.MetadataValue.int(total_records_deleted),
            },
        ) from e

    context.log.info(f"Completed chunk {chunk_min}-{chunk_max}: deleted {total_records_deleted} records")

    # Emit metric for chunk completion
    run_id = context.run.run_id
    try:
        metrics_client.increment(
            "distinct_ids_without_person_chunks_completed_total",
            labels={"job_name": job_name, "run_id": run_id, "chunk_id": chunk_id},
            value=1.0,
        ).result()
    except Exception:
        pass  # Don't fail on metrics error

    context.add_output_metadata(
        {
            "chunk_min": dagster.MetadataValue.int(chunk_min),
            "chunk_max": dagster.MetadataValue.int(chunk_max),
            "records_deleted": dagster.MetadataValue.int(total_records_deleted),
        }
    )

    return {
        "chunk_min": chunk_min,
        "chunk_max": chunk_max,
        "records_deleted": total_records_deleted,
    }


@dagster.job(
    tags={"owner": JobOwners.TEAM_INGESTION.value},
    executor_def=k8s_job_executor,
)
def delete_persons_from_trigger_log_job():
    """
    Scan posthog_person_deletes_log table, and deletes the corresponding posthog_person_new rows.
    """
    id_range = get_id_range_for_dpft()
    chunks = create_chunks_for_dpft(id_range)
    chunks.map(scan_delete_chunk_for_dpft)
