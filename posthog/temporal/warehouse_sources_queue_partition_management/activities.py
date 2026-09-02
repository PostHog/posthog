from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from django.conf import settings

import psycopg
import requests
import structlog
import temporalio.activity
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

PARTITIONED_TABLES = ["sourcebatch", "sourcebatchstatus"]
PARTITIONS_AHEAD = 7
RETENTION_DAYS = 7

# Dropping a partition needs ACCESS EXCLUSIVE on the parent, so a waiting DROP
# queues every reader of the queue behind it. Wait a few seconds, then give up:
# the error is recorded and alerted, and tomorrow's run retries.
DDL_LOCK_TIMEOUT_SECONDS = 5

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


@temporalio.activity.defn
async def manage_warehouse_sources_queue_partitions() -> dict:
    database_url: str = settings.WAREHOUSE_SOURCES_DATABASE_URL
    ensured: list[str] = []
    dropped: list[str] = []
    errors: list[str] = []

    with psycopg.Connection.connect(database_url, autocommit=True) as conn:
        conn.execute(f"SET lock_timeout = '{DDL_LOCK_TIMEOUT_SECONDS}s'")
        today = datetime.now(UTC).date()

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
            detached = _detached_partition_candidates(conn, table)
            for partition_name in _attached_partitions(conn, table) + detached:
                partition_date = _partition_date(partition_name)
                if partition_date is None:
                    continue
                if partition_date < cutoff:
                    if partition_name in detached and not _confirm_detached_partition(
                        conn, partition_name, partition_date, errors
                    ):
                        continue
                    if table == "sourcebatch":
                        try:
                            await sync_to_async(_terminalize_stranded_runs)(conn, partition_name)
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
                        conn.execute(f"DROP TABLE IF EXISTS {partition_name}")
                        dropped.append(partition_name)
                    except Exception as e:
                        errors.append(f"Failed to drop {partition_name}: {e}")
                        logger.exception("Failed to drop partition", partition=partition_name)

        _verify_partitions(conn, today, errors)

    s3_deleted = _cleanup_old_s3_extractions(today, errors)

    result = PartitionResult(ensured=ensured, dropped=dropped, errors=errors, s3_deleted=s3_deleted)

    logger.info(
        "Partition management completed",
        ensured_count=len(ensured),
        dropped_count=len(dropped),
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


def _partition_date(partition_name: str) -> date | None:
    """Parse the ``YYYYMMDD`` suffix of a daily partition. ``None`` if the name has no date."""
    suffix = partition_name.rsplit("_", 1)[-1]
    try:
        return date(int(suffix[:4]), int(suffix[4:6]), int(suffix[6:8]))
    except (ValueError, IndexError):
        return None


def _attached_partitions(conn: psycopg.Connection, table: str) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            """
            SELECT inhrelid::regclass::text AS partition_name
            FROM pg_inherits
            WHERE inhparent = %s::regclass
            ORDER BY inhrelid::regclass::text
            """,
            [table],
        ).fetchall()
    ]


def _detached_partition_candidates(conn: psycopg.Connection, table: str) -> list[str]:
    """Dated tables that no longer hang off the parent.

    A detached partition disappears from ``pg_inherits``, so the attached scan
    alone would keep it and its indexes forever. Match on the name instead. The
    pattern is anchored, so ``sourcebatch`` never claims a ``sourcebatchstatus``
    table.

    These are candidates, not confirmed partitions: run
    ``_confirm_detached_partition`` before dropping one.
    """
    return [
        row[0]
        for row in conn.execute(
            """
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
              AND n.nspname = ANY (current_schemas(false))
              AND c.relname ~ %s
              AND NOT EXISTS (SELECT 1 FROM pg_inherits WHERE inhrelid = c.oid)
            ORDER BY c.relname
            """,
            [f"^{table}_[0-9]{{8}}$"],
        ).fetchall()
    ]


def _confirm_detached_partition(
    conn: psycopg.Connection,
    partition_name: str,
    partition_date: date,
    errors: list[str],
) -> bool:
    """Confirm a name-matched table really is a former daily partition.

    Postgres keeps no record that a table was once a partition, so the name alone
    would also match, and then drop, a hand-made table such as a backup taken
    during an incident. A real detached partition still holds only the rows its
    range constraint allowed, which a copy of the parent does not. Anything that
    fails or cannot be checked, including a missing ``created_at`` column, keeps
    the table and reports why.
    """
    try:
        outside = conn.execute(
            f"SELECT 1 FROM {partition_name} WHERE created_at < %s OR created_at >= %s LIMIT 1",
            [partition_date, partition_date + timedelta(days=1)],
        ).fetchall()
    except Exception as e:
        errors.append(f"Cannot confirm {partition_name} is a detached partition, keeping it: {e}")
        logger.exception("Cannot confirm detached partition", partition=partition_name)
        return False

    if outside:
        errors.append(
            f"{partition_name} holds rows outside {partition_date.isoformat()}, "
            f"so it is not a detached partition, keeping it"
        )
        logger.warning("Name matches a partition but the rows do not", partition=partition_name)
        return False

    return True


def _terminalize_stranded_runs(conn: psycopg.Connection, partition_name: str) -> None:
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
    stranded = conn.execute(
        f"""
        SELECT run_uuid, team_id, schema_id, job_id,
               MAX(metadata->>'workflow_run_id') AS workflow_run_id,
               COUNT(*) AS non_terminal_batches
        FROM {partition_name}
        WHERE latest_state IN ({states})
        GROUP BY run_uuid, team_id, schema_id, job_id
        ORDER BY run_uuid
        """
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
    cutoff = today - timedelta(days=RETENTION_DAYS)
    for table in PARTITIONED_TABLES:
        attached = set(_attached_partitions(conn, table))

        for offset in range(PARTITIONS_AHEAD):
            d = today + timedelta(days=offset)
            expected = f"{table}_{d.strftime('%Y%m%d')}"
            if expected not in attached:
                errors.append(f"Partition {expected} missing after creation attempt")

        # Nothing else in the system notices unreclaimed partitions, so retention
        # can drift for months in silence. Report the leftovers as a failure.
        expired = sorted(
            name
            for name in attached.union(_detached_partition_candidates(conn, table))
            if (partition_date := _partition_date(name)) is not None and partition_date < cutoff
        )
        if expired:
            errors.append(
                f"{table} partitions older than {RETENTION_DAYS} days survived retention: "
                f"{', '.join(expired[:5])} (total {len(expired)})"
            )

        # Rows that fall outside every daily partition land here. Retention is keyed
        # on the partition name, so it can never reclaim them, and their presence
        # also makes the next CREATE ... PARTITION OF fail.
        #
        # This probe takes ACCESS SHARE on the default partition, so a concurrent
        # drop holding ACCESS EXCLUSIVE trips the session lock_timeout here. Record
        # the failure and continue, so a blocked or missing probe does not abort the
        # run before the S3 cleanup and Slack alert that follow it.
        try:
            if conn.execute(f"SELECT 1 FROM {table}_default LIMIT 1").fetchall():
                errors.append(f"{table}_default holds rows: retention cannot reclaim them")
        except Exception as e:
            errors.append(f"Failed to check {table}_default for rows: {e}")
            logger.exception("Failed to check default partition for rows", table=table)


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
