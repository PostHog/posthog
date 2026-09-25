from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from django.conf import settings

import psycopg
import requests
import structlog
import temporalio.activity

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async_pool

logger = structlog.get_logger(__name__)

PARTITIONED_TABLES = ["sourcebatch", "sourcebatchstatus"]
PARTITIONS_AHEAD = 7
RETENTION_DAYS = 7
DEFAULT_PARTITION_DELETE_BATCH_SIZE = 10_000

# Deliberately not the lock-takeover sentinel — that string has special
# downstream semantics in the dead-job gate.
RETENTION_STRANDED_ERROR = "batches aged out of retention without being processed"

# Batch states that mean a run is still owed work (mirrors the non-terminal
# set in postgres_queue/jobs_db.py; 'pending' = never claimed).
_NON_TERMINAL_BATCH_STATES = ("pending", "waiting", "waiting_retry", "executing")


@dataclass(frozen=True, slots=True)
class PartitionResult:
    ensured: list[str]
    dropped: list[str]
    errors: list[str]
    s3_deleted: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@frozen
class _PartitionChanges:
    ensured: list[str]
    dropped: list[str]


@temporalio.activity.defn
async def manage_warehouse_sources_queue_partitions() -> dict:
    errors: list[str] = []
    today = datetime.now(UTC).date()

    # The connection sets no lock_timeout, so partition DDL can wait on a lock for an unbounded time.
    # Run the database work on the general thread pool so that the wait blocks neither the worker's
    # event loop nor the single thread shared by all thread-sensitive work in the process.
    changes = await database_sync_to_async_pool(_manage_database_partitions)(today, errors)

    s3_deleted = _cleanup_old_s3_extractions(today, errors)

    result = PartitionResult(ensured=changes.ensured, dropped=changes.dropped, errors=errors, s3_deleted=s3_deleted)

    logger.info(
        "Partition management completed",
        ensured_count=len(result.ensured),
        dropped_count=len(result.dropped),
        s3_deleted_count=len(s3_deleted),
        error_count=len(errors),
        success=result.success,
    )

    if not result.success:
        _send_slack_failure(errors)

    return {
        "ensured": result.ensured,
        "dropped": result.dropped,
        "s3_deleted": result.s3_deleted,
        "errors": result.errors,
        "success": result.success,
    }


def _manage_database_partitions(today: date, errors: list[str]) -> _PartitionChanges:
    ensured: list[str] = []
    dropped: list[str] = []

    with psycopg.Connection.connect(_partition_ddl_database_url(), autocommit=True) as conn:
        for table in PARTITIONED_TABLES:
            for offset in range(PARTITIONS_AHEAD):
                d = today + timedelta(days=offset)
                partition_name = f"{table}_{d.strftime('%Y%m%d')}"
                try:
                    conn.execute(
                        f"CREATE TABLE IF NOT EXISTS {partition_name} "
                        f"PARTITION OF {table} "
                        f"FOR VALUES FROM ('{d.isoformat()}') TO ('{(d + timedelta(days=1)).isoformat()}')"
                    )
                    ensured.append(partition_name)
                except Exception as e:
                    errors.append(f"Failed to create {partition_name}: {e}")
                    logger.exception("Failed to create partition", partition=partition_name)

        cutoff = today - timedelta(days=RETENTION_DAYS)
        for table in PARTITIONED_TABLES:
            for row in conn.execute(
                """
                SELECT inhrelid::regclass::text AS partition_name
                FROM pg_inherits
                WHERE inhparent = %s::regclass
                ORDER BY inhrelid::regclass::text
                """,
                [table],
            ).fetchall():
                partition_name = row[0]
                if partition_name.endswith("_default"):
                    _expire_default_partition_rows(conn, table, partition_name, cutoff, errors)
                    continue
                suffix = partition_name.rsplit("_", 1)[-1]
                try:
                    partition_date = date(int(suffix[:4]), int(suffix[4:6]), int(suffix[6:8]))
                except (ValueError, IndexError):
                    continue
                if partition_date < cutoff:
                    if table == "sourcebatch":
                        try:
                            _terminalize_stranded_runs(conn, partition_name)
                        except Exception as e:
                            # Keep the partition as evidence while the alert is live;
                            # partitions are daily and small, so retrying tomorrow is cheap.
                            errors.append(f"Failed to terminalize stranded runs in {partition_name}: {e}")
                            logger.exception(
                                "Failed to terminalize stranded runs before partition drop",
                                partition=partition_name,
                            )
                            continue
                    try:
                        _drop_partition(conn, partition_name)
                        dropped.append(partition_name)
                    except Exception as e:
                        errors.append(f"Failed to drop {partition_name}: {e}")
                        logger.exception("Failed to drop partition", partition=partition_name)

        _verify_partitions(conn, today, errors)

    return _PartitionChanges(ensured=ensured, dropped=dropped)


def _partition_ddl_database_url() -> str:
    # Only the owner of a partitioned table can create its partitions, and the migration role owns the queue tables.
    return settings.WAREHOUSE_SOURCES_QUEUE_PARTITION_DATABASE_URL or settings.WAREHOUSE_SOURCES_DATABASE_URL


def _drop_partition(conn: psycopg.Connection, partition_name: str) -> None:
    try:
        conn.execute(f"DROP TABLE IF EXISTS {partition_name}")
    except psycopg.errors.InsufficientPrivilege:
        # Only a table's owner can drop it. Partitions created before this job used the
        # migration role are owned by the worker's own role, so drop those with that role.
        if not settings.WAREHOUSE_SOURCES_QUEUE_PARTITION_DATABASE_URL:
            raise
        with psycopg.Connection.connect(settings.WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as owner_conn:
            owner_conn.execute(f"DROP TABLE IF EXISTS {partition_name}")


def _expire_default_partition_rows(
    conn: psycopg.Connection, table: str, partition_name: str, cutoff: date, errors: list[str]
) -> None:
    """Apply retention to rows in the default partition.

    Rows land in the default partition only for days that had no daily partition. Retention
    removes data by dropping daily partitions, so without this step those rows stay forever.
    """
    created_before = datetime.combine(cutoff, datetime.min.time(), tzinfo=UTC)
    try:
        if table == "sourcebatch":
            _terminalize_stranded_runs(conn, partition_name, created_before=created_before)
        deleted = 0
        while True:
            # Bounded batches keep each statement short after an outage leaves several days of rows.
            batch_deleted = conn.execute(
                f"""
                DELETE FROM {partition_name}
                WHERE ctid = ANY(ARRAY(
                    SELECT ctid FROM {partition_name}
                    WHERE created_at < %(created_before)s
                    LIMIT %(limit)s
                ))
                """,
                {"created_before": created_before, "limit": DEFAULT_PARTITION_DELETE_BATCH_SIZE},
            ).rowcount
            deleted += batch_deleted
            if batch_deleted < DEFAULT_PARTITION_DELETE_BATCH_SIZE:
                break
    except Exception as e:
        errors.append(f"Failed to expire old rows in {partition_name}: {e}")
        logger.exception("Failed to expire old default partition rows", partition=partition_name)
        return
    if deleted:
        logger.warning("Expired old default partition rows", partition=partition_name, deleted=deleted)


def _terminalize_stranded_runs(
    conn: psycopg.Connection, partition_name: str, *, created_before: datetime | None = None
) -> None:
    """Fail runs that still have non-terminal batches in ``partition_name`` before it is dropped.

    Dropping the data itself is deliberate — the staged cursor never promoted,
    so the next run re-extracts. What must not happen silently is the run: with
    its batches gone, the final batch never arrives, the ExternalDataJob stays
    RUNNING forever, no terminal status means no app_metrics2 alert, and the
    pipeline lock stays held. So fail the run's batches (the whole run — runs
    span partitions, and leftover claimable siblings could resurrect the job),
    mark the job Failed, and release the schema lock.

    Fail-closed: any error propagates so the caller records it and skips the
    drop, preserving the evidence for the retry.
    """
    from django.db import close_old_connections

    from products.warehouse_sources.backend.facade.pipelines import (
        BatchQueue,
        mark_job_failed_if_not_terminal,
        release_v3_pipeline_lock,
    )

    states = ", ".join(f"'{s}'" for s in _NON_TERMINAL_BATCH_STATES)
    created_filter = "AND created_at < %(created_before)s" if created_before else ""
    stranded = conn.execute(
        f"""
        SELECT run_uuid, team_id, schema_id, job_id,
               MAX(metadata->>'workflow_run_id') AS workflow_run_id,
               COUNT(*) AS non_terminal_batches
        FROM {partition_name}
        WHERE latest_state IN ({states})
          {created_filter}
        GROUP BY run_uuid, team_id, schema_id, job_id
        ORDER BY run_uuid
        """,
        {"created_before": created_before} if created_before else None,
    ).fetchall()
    if not stranded:
        return

    # Drop stale app-DB connections so the job-status writes reconnect instead of erroring.
    close_old_connections()

    runs_failed: list[dict[str, Any]] = []
    total_failed_batches = 0
    for run_uuid, team_id, schema_id, job_id, workflow_run_id, non_terminal_batches in stranded:
        # Batches are failed LAST — the inverse of the takeover ordering, which is
        # safe here because these batches are past CLAIM_ELIGIBILITY_INTERVAL and
        # can never be claimed. Failing them first would flip the very state this
        # sweep uses to rediscover the run, so a crash between the two DBs
        # (autocommit, no cross-DB atomicity) would strand the job invisibly.
        mark_job_failed_if_not_terminal(job_id=job_id, team_id=team_id, error=RETENTION_STRANDED_ERROR)
        lock_released: bool | None = None
        if workflow_run_id:
            lock_released = release_v3_pipeline_lock(team_id, schema_id, workflow_run_id)
        total_failed_batches += BatchQueue.fail_batches_for_job_sync(
            conn, job_id=job_id, reason=RETENTION_STRANDED_ERROR
        )
        runs_failed.append(
            {
                "run_uuid": run_uuid,
                "team_id": team_id,
                "schema_id": schema_id,
                "job_id": job_id,
                "non_terminal_batches": non_terminal_batches,
                # False also covers benign cases (already expired / taken over),
                # so this is observability only — never gate the drop on it.
                "lock_released": lock_released,
            }
        )

    logger.warning(
        "Terminalized stranded runs before partition drop",
        partition=partition_name,
        runs_failed=len(runs_failed),
        failed_batches=total_failed_batches,
        runs=runs_failed,
    )


def _cleanup_old_s3_extractions(today: date, errors: list[str]) -> list[str]:
    """Delete S3 date-partitioned extraction prefixes older than RETENTION_DAYS."""
    from products.data_warehouse.backend.facade.api import get_s3_client

    s3 = get_s3_client()
    base_prefix = f"{settings.DATAWAREHOUSE_BUCKET}/data_pipelines_extract"
    cutoff = today - timedelta(days=RETENTION_DAYS)
    deleted: list[str] = []

    try:
        entries = s3.ls(base_prefix)
    except FileNotFoundError:
        logger.debug("s3_extraction_prefix_not_found", prefix=base_prefix)
        return deleted
    except Exception as e:
        # Record instead of raising, because a raise here skips the Slack alert for every error so far.
        errors.append(f"Failed to list S3 extraction partitions: {e}")
        logger.exception("Failed to list S3 extraction partitions", prefix=base_prefix)
        return deleted

    for entry in entries:
        name = entry.rstrip("/").rsplit("/", 1)[-1]
        if not name.startswith("dt="):
            continue
        try:
            partition_date = date.fromisoformat(name[3:])
        except ValueError:
            continue
        if partition_date < cutoff:
            try:
                s3.delete(entry, recursive=True)
                deleted.append(name)
                logger.debug("s3_extraction_partition_deleted", partition=name)
            except Exception as e:
                errors.append(f"Failed to delete S3 partition {name}: {e}")
                logger.exception("Failed to delete S3 extraction partition", partition=name)

    return deleted


def _verify_partitions(conn: psycopg.Connection, today: date, errors: list[str]) -> None:
    for table in PARTITIONED_TABLES:
        existing = set()
        for row in conn.execute(
            """
            SELECT inhrelid::regclass::text AS partition_name
            FROM pg_inherits
            WHERE inhparent = %s::regclass
            """,
            [table],
        ).fetchall():
            existing.add(row[0])

        for offset in range(PARTITIONS_AHEAD):
            d = today + timedelta(days=offset)
            expected = f"{table}_{d.strftime('%Y%m%d')}"
            if expected not in existing:
                errors.append(f"Partition {expected} missing after creation attempt")


def _send_slack_failure(errors: list[str]) -> None:
    webhook_url = settings.WAREHOUSE_SOURCES_QUEUE_PARTITION_SLACK_WEBHOOK_URL
    if not webhook_url:
        logger.warning("No Slack webhook configured for partition management alerts")
        return

    error_text = "\n".join(f"- {e}" for e in errors[:10])
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":rotating_light: *Warehouse sources queue partition management failed*",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```{error_text}```",
            },
        },
    ]

    try:
        response = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to send Slack notification", error=str(e))
