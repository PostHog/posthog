"""Dagster job for backfilling posthog_persons data from source to destination Postgres database."""

import os
import time
from typing import Any

import dagster
import psycopg2
import psycopg2.errors
from dagster_k8s import k8s_job_executor

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.dags.common import JobOwners


class PersonsNewBackfillConfig(dagster.Config):
    """Configuration for the persons new backfill job."""

    chunk_size: int = 1_000_000  # ID range per chunk
    batch_size: int = 100_000  # Records per batch insert
    source_table: str = "posthog_persons"
    destination_table: str = "posthog_persons_new"
    min_id: int | None = None  # Optional override for min ID to resume from partial state
    max_id: int | None = None  # Optional override for max ID to resume from partial state


@dagster.op
def get_id_range_for_pnb(
    context: dagster.OpExecutionContext,
    config: PersonsNewBackfillConfig,
    database: dagster.ResourceParam[psycopg2.extensions.connection],
) -> tuple[int, int]:
    """
    Query source database for MIN(id) and optionally MAX(id) from posthog_persons table.
    If max_id is provided in config, uses that instead of querying.
    Returns tuple (min_id, max_id).
    """
    with database.cursor() as cursor:
        # Use config min_id if provided, otherwise query database
        if config.min_id is not None:
            min_id = config.min_id
            context.log.info(f"Using configured min_id override: {config.min_id}")
        else:
            # Always query for min_id
            min_query = f"SELECT MIN(id) as min_id FROM {config.source_table}"
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
            max_query = f"SELECT MAX(id) as max_id FROM {config.source_table}"
            context.log.info(f"Querying max ID: {max_query}")
            cursor.execute(max_query)
            max_result = cursor.fetchone()

            if max_result is None or max_result["max_id"] is None:
                context.log.exception("Source table has no valid max ID")
                # Note: No metrics client here as this is get_id_range op, not copy_chunk
                raise dagster.Failure("Source table has no valid max ID")

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
def create_chunks_for_pnb(
    context: dagster.OpExecutionContext,
    config: PersonsNewBackfillConfig,
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
def copy_chunk(
    context: dagster.OpExecutionContext,
    config: PersonsNewBackfillConfig,
    chunk: tuple[int, int],
    database: dagster.ResourceParam[psycopg2.extensions.connection],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dict[str, Any]:
    """
    Copy a chunk of records from source to destination database.
    Processes in batches of batch_size records.
    """
    chunk_min, chunk_max = chunk
    batch_size = config.batch_size
    source_table = config.source_table
    destination_table = config.destination_table
    chunk_id = f"chunk_{chunk_min}_{chunk_max}"
    job_name = context.run.job_name

    # Initialize metrics client
    metrics_client = MetricsClient(cluster)

    context.log.info(f"Starting chunk copy: {chunk_min} to {chunk_max}")

    total_records_copied = 0
    batch_start_id = chunk_min
    failed_batch_start_id: int | None = None

    try:
        with database.cursor() as cursor:
            # Set session-level settings once for the entire chunk
            cursor.execute("SET application_name = 'backfill_posthog_persons_to_posthog_persons_new'")
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
                    records_attempted = batch_end_id - batch_start_id
                    if records_attempted <= 0:
                        break
                    # Begin transaction (settings already applied at session level)
                    cursor.execute("BEGIN")

                    # Execute INSERT INTO ... SELECT with NOT EXISTS check
                    insert_query = f"""
INSERT INTO {destination_table}
SELECT s.*
FROM {source_table} s
WHERE s.id >= %s AND s.id <= %s
  AND NOT EXISTS (
    SELECT 1
    FROM {destination_table} d
    WHERE d.team_id = s.team_id
      AND d.id = s.id
  )
ORDER BY s.id DESC
"""
                    cursor.execute(insert_query, (batch_start_id, batch_end_id))
                    records_inserted = cursor.rowcount

                    # Commit the transaction
                    cursor.execute("COMMIT")

                    try:
                        metrics_client.increment(
                            "persons_new_backfill_records_attempted_total",
                            labels={"job_name": job_name, "chunk_id": chunk_id},
                            value=float(records_attempted),
                        ).result()
                    except Exception:
                        pass  # Don't fail on metrics error

                    batch_duration_seconds = time.time() - batch_start_time

                    try:
                        metrics_client.increment(
                            "persons_new_backfill_records_inserted_total",
                            labels={"job_name": job_name, "chunk_id": chunk_id},
                            value=float(records_inserted),
                        ).result()
                    except Exception:
                        pass  # Don't fail on metrics error

                    try:
                        metrics_client.increment(
                            "persons_new_backfill_batches_copied_total",
                            labels={"job_name": job_name, "chunk_id": chunk_id},
                            value=1.0,
                        ).result()
                    except Exception:
                        pass
                    # Track batch duration metric (IV)
                    try:
                        metrics_client.increment(
                            "persons_new_backfill_batch_duration_seconds_total",
                            labels={"job_name": job_name, "chunk_id": chunk_id},
                            value=batch_duration_seconds,
                        ).result()
                    except Exception:
                        pass

                    total_records_copied += records_inserted

                    context.log.info(
                        f"Copied batch: {records_inserted} records "
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

                    # Check if error is a duplicate key violation, pause and retry if so
                    is_unique_violation = isinstance(batch_error, psycopg2.errors.UniqueViolation) or (
                        isinstance(batch_error, psycopg2.Error) and getattr(batch_error, "pgcode", None) == "23505"
                    )
                    if is_unique_violation:
                        error_msg = (
                            f"Duplicate key violation detected for batch starting at ID {batch_start_id} "
                            f"in chunk {chunk_min}-{chunk_max}. Error is: {batch_error}. "
                            "This is expected if records already exist in destination table. "
                        )
                        context.log.warning(error_msg)
                        if retry_attempt < 3:
                            retry_attempt += 1
                            context.log.info(f"Retrying batch {retry_attempt} of 3...")
                            time.sleep(1)
                            continue

                    failed_batch_start_id = batch_start_id
                    error_msg = (
                        f"Failed to copy batch starting at ID {batch_start_id} "
                        f"in chunk {chunk_min}-{chunk_max}: {str(batch_error)}"
                    )
                    context.log.exception(error_msg)
                    # Report fatal error metric before raising
                    try:
                        metrics_client.increment(
                            "persons_new_backfill_error",
                            labels={"job_name": job_name, "chunk_id": chunk_id, "reason": "batch_copy_failed"},
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
                            "records_copied_before_failure": dagster.MetadataValue.int(total_records_copied),
                        },
                    ) from batch_error

    except dagster.Failure:
        # Re-raise Dagster failures as-is (they already have metadata and metrics)
        raise
    except Exception as e:
        # Catch any other unexpected errors
        error_msg = f"Unexpected error copying chunk {chunk_min}-{chunk_max}: {str(e)}"
        context.log.exception(error_msg)
        # Report fatal error metric before raising
        try:
            metrics_client.increment(
                "persons_new_backfill_error",
                labels={"job_name": job_name, "chunk_id": chunk_id, "reason": "unexpected_copy_error"},
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
                "records_copied_before_failure": dagster.MetadataValue.int(total_records_copied),
            },
        ) from e

    context.log.info(f"Completed chunk {chunk_min}-{chunk_max}: copied {total_records_copied} records")

    # Emit metric for chunk completion
    run_id = context.run.run_id
    try:
        metrics_client.increment(
            "persons_new_backfill_chunks_completed_total",
            labels={"job_name": job_name, "run_id": run_id, "chunk_id": chunk_id},
            value=1.0,
        ).result()
    except Exception:
        pass  # Don't fail on metrics error

    context.add_output_metadata(
        {
            "chunk_min": dagster.MetadataValue.int(chunk_min),
            "chunk_max": dagster.MetadataValue.int(chunk_max),
            "records_copied": dagster.MetadataValue.int(total_records_copied),
        }
    )

    return {
        "chunk_min": chunk_min,
        "chunk_max": chunk_max,
        "records_copied": total_records_copied,
    }


@dagster.asset
def postgres_env_check(context: dagster.AssetExecutionContext) -> None:
    """
    Simple asset that prints PostgreSQL environment variables being used.
    Useful for debugging connection configuration.
    """
    env_vars = {
        "POSTGRES_HOST": os.getenv("POSTGRES_HOST", "not set"),
        "POSTGRES_PORT": os.getenv("POSTGRES_PORT", "not set"),
        "POSTGRES_DATABASE": os.getenv("POSTGRES_DATABASE", "not set"),
        "POSTGRES_USER": os.getenv("POSTGRES_USER", "not set"),
        "POSTGRES_PASSWORD": "***" if os.getenv("POSTGRES_PASSWORD") else "not set",
    }

    context.log.info("PostgreSQL environment variables:")
    for key, value in env_vars.items():
        context.log.info(f"  {key}: {value}")


@dagster.job(
    tags={"owner": JobOwners.TEAM_INGESTION.value},
    executor_def=k8s_job_executor,
)
def persons_new_backfill_job():
    """
    Backfill posthog_persons data from source to destination Postgres database.
    Divides the ID space into chunks and processes them in parallel.
    """
    id_range = get_id_range_for_pnb()
    chunks = create_chunks_for_pnb(id_range)
    chunks.map(copy_chunk)
