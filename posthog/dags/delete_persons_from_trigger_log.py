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
from posthog.dags.common import JobOwners

MAX_RETRY_ATTEMPTS = 5


class DeletePersonsFromTriggerLogConfig(dagster.Config):
    """Configuration for the delete persons from trigger log job."""

    persons_table: str = "posthog_person_new"
    batch_size: int = 100  # Work in small batches since each person ID will cascade a delete to many distinct ID rows


@dagster.op
def get_team_ids_for_dpft(
    context: dagster.OpExecutionContext,
    database: dagster.ResourceParam[psycopg2.extensions.connection],
) -> list[int]:
    """
    Query source database for all distinct team_ids from posthog_person_deletes_log table
    that have corresponding records in posthog_person_new.
    Returns list of team IDs to process.
    """
    with database.cursor() as cursor:
        team_ids_query = """
            SELECT DISTINCT pdl.team_id
            FROM posthog_person_deletes_log AS pdl
            WHERE EXISTS (
                SELECT 1
                FROM posthog_person_new AS p
                WHERE pdl.id = p.id AND pdl.team_id = p.team_id
            )
            ORDER BY pdl.team_id
        """
        context.log.info("Querying for distinct team_ids with persons to delete")
        cursor.execute(team_ids_query)
        rows = cursor.fetchall()

        team_ids = [int(row["team_id"]) for row in rows]

        if not team_ids:
            context.log.info("No team IDs found with persons to delete")
            return []

        context.log.info(f"Found {len(team_ids)} teams with persons to delete")
        context.log.info(f"Sample of teams to process: {team_ids[:10]}" + ("..." if len(team_ids) > 10 else ""))
        context.add_output_metadata(
            {
                "team_count": dagster.MetadataValue.int(len(team_ids)),
            }
        )

        return team_ids


@dagster.op(out=dagster.DynamicOut(int))
def create_team_chunks_for_dpft(
    context: dagster.OpExecutionContext,
    team_ids: list[int],
):
    """
    Create a chunk for each team_id.
    Yields DynamicOutput for each team.
    """
    if not team_ids:
        context.log.info("No teams to process")
        return

    context.log.info(f"Creating {len(team_ids)} team chunks")

    for team_id in team_ids:
        chunk_key = f"team_{team_id}"
        context.log.info(f"Yielding chunk for team_id: {team_id}")
        yield dagster.DynamicOutput(
            value=team_id,
            mapping_key=chunk_key,
        )


@dagster.op
def scan_delete_chunk_for_dpft(
    context: dagster.OpExecutionContext,
    config: DeletePersonsFromTriggerLogConfig,
    chunk: int,
    database: dagster.ResourceParam[psycopg2.extensions.connection],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dict[str, Any]:
    """
    Scan posthog_person_deletes_log table for all records of a specific team_id
    that have an associated posthog_person_new row, and deletes the corresponding
    posthog_person_new rows. Processes in batches of batch_size person IDs.
    """
    team_id = chunk
    batch_size = config.batch_size
    chunk_id = f"team_{team_id}"
    job_name = context.run.job_name

    # Initialize metrics client
    metrics_client = MetricsClient(cluster)

    context.log.info(f"Starting chunk scan and delete for team_id: {team_id}")

    total_records_deleted = 0
    last_person_id: int | None = None
    failed_last_person_id: int | None = None

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
            while True:
                try:
                    # Track batch start time for duration metric
                    batch_start_time = time.time()

                    # Begin transaction (settings already applied at session level)
                    cursor.execute("BEGIN")

                    # Query to find posthog_person_deletes_log rows for this team
                    # Use keyset pagination with WHERE id > last_id for efficiency
                    if last_person_id is None:
                        scan_query = f"""
SELECT pdl.id, pdl.team_id
FROM posthog_person_deletes_log AS pdl
WHERE pdl.team_id = %s
  AND EXISTS (
    SELECT 1
    FROM {config.persons_table} AS p
    WHERE pdl.id = p.id
      AND pdl.team_id = p.team_id
  )
ORDER BY pdl.id
LIMIT %s
"""
                        cursor.execute(scan_query, (team_id, batch_size))
                    else:
                        scan_query = f"""
SELECT pdl.id, pdl.team_id
FROM posthog_person_deletes_log AS pdl
WHERE pdl.team_id = %s
  AND pdl.id > %s
  AND EXISTS (
    SELECT 1
    FROM {config.persons_table} AS p
    WHERE pdl.id = p.id
      AND pdl.team_id = p.team_id
  )
ORDER BY pdl.id
LIMIT %s
"""
                        cursor.execute(scan_query, (team_id, last_person_id, batch_size))

                    rows = cursor.fetchall()

                    # If no more rows, we're done with this team
                    if not rows:
                        cursor.execute("COMMIT")
                        break

                    ids_to_delete = [(int(row["team_id"]), int(row["id"])) for row in rows]
                    # Update last_person_id for next iteration
                    last_person_id = ids_to_delete[-1][1]

                    # Commit the transaction
                    cursor.execute("COMMIT")

                    records_deleted = 0
                    for tid, person_id in ids_to_delete:
                        try:
                            context.log.info(
                                f"Deleting person={person_id}, team_id={tid} from {config.persons_table} "
                                f"(attempt {retry_attempt + 1})"
                            )
                            cursor.execute("BEGIN")
                            cursor.execute(
                                f"DELETE FROM {config.persons_table} WHERE team_id = %s AND id = %s",
                                (tid, person_id),
                            )
                            records_deleted += cursor.rowcount
                            cursor.execute("COMMIT")
                        except Exception as delete_error:
                            # bubble up errors to be retried on deadlock etc. or fail the job
                            context.log.exception(
                                f"Failed to delete person={person_id}, team_id={tid} from "
                                f"{config.persons_table} (attempt {retry_attempt + 1}): {delete_error}"
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
                            "delete_persons_from_trigger_log_records_scanned_total",
                            labels={"job_name": job_name, "chunk_id": chunk_id},
                            value=float(batch_size),
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
                        f"Deleted batch: {records_deleted} records for team_id={team_id}, "
                        f"last_person_id={last_person_id}"
                    )

                    # Reset retry attempt counter after successful batch
                    retry_attempt = 0

                except Exception as batch_error:
                    # Rollback transaction on error
                    try:
                        cursor.execute("ROLLBACK")
                    except Exception as rollback_error:
                        context.log.exception(
                            f"Failed to rollback transaction for team_id={team_id}, "
                            f"last_person_id={last_person_id}: {str(rollback_error)}"
                        )
                        pass  # Ignore rollback errors

                    # Check if error is a serialization failure, pause and retry if so
                    serialization_failure_class = getattr(psycopg2.errors, "SerializationFailure", None)
                    is_serialization_failure = (
                        serialization_failure_class is not None and isinstance(batch_error, serialization_failure_class)
                    ) or (isinstance(batch_error, psycopg2.Error) and getattr(batch_error, "pgcode", None) == "40001")
                    if is_serialization_failure:
                        error_msg = (
                            f"Serialization failure detected for team_id={team_id}, "
                            f"last_person_id={last_person_id}. Error is: {batch_error}. "
                            "This is expected due to concurrent transactions."
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
                            f"Deadlock detected for team_id={team_id}, "
                            f"last_person_id={last_person_id}. Error is: {batch_error}. "
                            "This is expected due to concurrent transactions."
                        )
                        context.log.warning(error_msg)
                        if retry_attempt < MAX_RETRY_ATTEMPTS:
                            retry_attempt += 1
                            context.log.warning(f"Retrying batch {retry_attempt} of {MAX_RETRY_ATTEMPTS}...")
                            time.sleep(1)
                            continue

                    # Handle unexpected errors by bubbling up to dagster.Failure
                    failed_last_person_id = last_person_id
                    error_msg = (
                        f"Failed to scan and delete rows for team_id={team_id}, "
                        f"last_person_id={last_person_id}: {str(batch_error)}"
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
                            "team_id": dagster.MetadataValue.int(team_id),
                            "failed_last_person_id": dagster.MetadataValue.int(failed_last_person_id)
                            if failed_last_person_id
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
        error_msg = f"Unexpected error scanning and deleting for team_id={team_id}: {str(e)}"
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
                "team_id": dagster.MetadataValue.int(team_id),
                "failed_last_person_id": dagster.MetadataValue.int(failed_last_person_id)
                if failed_last_person_id
                else dagster.MetadataValue.int(last_person_id)
                if last_person_id
                else dagster.MetadataValue.text("N/A"),
                "error_message": dagster.MetadataValue.text(str(e)),
                "records_deleted_before_failure": dagster.MetadataValue.int(total_records_deleted),
            },
        ) from e

    context.log.info(f"Completed team_id={team_id}: deleted {total_records_deleted} records")

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
            "team_id": dagster.MetadataValue.int(team_id),
            "records_deleted": dagster.MetadataValue.int(total_records_deleted),
        }
    )

    return {
        "team_id": team_id,
        "records_deleted": total_records_deleted,
    }


@dagster.job(
    tags={"owner": JobOwners.TEAM_INGESTION.value},
    executor_def=k8s_job_executor,
)
def delete_persons_from_trigger_log_job():
    """
    Scan posthog_person_deletes_log table by team_id, and deletes the corresponding
    posthog_person_new rows. Each team is processed in parallel for optimal performance.
    """
    team_ids = get_team_ids_for_dpft()
    chunks = create_team_chunks_for_dpft(team_ids)
    chunks.map(scan_delete_chunk_for_dpft)
