from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from django.conf import settings

import psycopg
import requests
import structlog
import temporalio.activity
from asgiref.sync import sync_to_async

from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.warehouse_sources_queue_partition_management.schedule import SCHEDULE_ID

logger = structlog.get_logger(__name__)

PARTITIONED_TABLES = ["sourcebatch", "sourcebatchstatus", "queuejob", "queuejobstatus"]
PARTITIONS_AHEAD = 7
RETENTION_DAYS = 7
DEFAULT_PARTITION_DELETE_BATCH_SIZE = 10_000

# Rows in these tables change state in place two or three times, and each change leaves a dead
# entry in the partial indexes on latest_state. A scale factor waits for 10% of a partition to be
# dead, which late in the day is ~150k rows, and the claim query then reads through those entries.
# A fixed threshold keeps the dead count low and about constant as the daily partition grows.
_IN_PLACE_UPDATE_TABLES = ("sourcebatch", "queuejob")
_PARTITION_AUTOVACUUM_OPTIONS = (
    "autovacuum_vacuum_scale_factor=0",
    "autovacuum_vacuum_threshold=10000",
    "autovacuum_analyze_scale_factor=0.02",
    "autovacuum_vacuum_cost_delay=2",
    "autovacuum_vacuum_cost_limit=2000",
)

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

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


@frozen
class _PartitionChanges:
    ensured: list[str]
    dropped: list[str]
    alerts: list[str]


@temporalio.activity.defn
async def manage_warehouse_sources_queue_partitions() -> dict:
    errors: list[str] = []
    today = datetime.now(UTC).date()

    # The connection sets no lock_timeout, so partition DDL can wait on a lock for an unbounded time.
    # Run the database work on the general thread pool so that the wait blocks neither the worker's
    # event loop nor the single thread shared by all thread-sensitive work in the process.
    changes = await database_sync_to_async_pool(_manage_database_partitions)(today, errors)

    result = PartitionResult(ensured=changes.ensured, dropped=changes.dropped, errors=errors)

    logger.info(
        "Partition management completed",
        ensured_count=len(result.ensured),
        dropped_count=len(result.dropped),
        error_count=len(errors),
        success=result.success,
        alerts=changes.alerts,
    )

    if changes.alerts:
        await sync_to_async(_send_slack_alert, thread_sensitive=False)(changes.alerts)

    return {
        "ensured": result.ensured,
        "dropped": result.dropped,
        "errors": result.errors,
        "alerts": changes.alerts,
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
                    continue
                if table in _IN_PLACE_UPDATE_TABLES:
                    _tune_partition_autovacuum(conn, partition_name, errors)

        cutoff = today - timedelta(days=RETENTION_DAYS)
        failed_default_expiries: set[str] = set()
        for table in PARTITIONED_TABLES:
            for partition_name in _list_partitions(conn, table):
                if partition_name.endswith("_default"):
                    if not _expire_default_partition_rows(conn, table, partition_name, cutoff, errors):
                        failed_default_expiries.add(partition_name)
                    continue
                partition_date = _partition_date(partition_name)
                if partition_date is None:
                    continue
                if partition_date < cutoff:
                    if table == "sourcebatch":
                        try:
                            _terminalize_stranded_runs(conn, partition_name)
                        except Exception as e:
                            # Keep the partition as evidence. Partitions are daily and small,
                            # so retrying tomorrow is cheap.
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

        alerts = _find_partition_alerts(conn, today, failed_default_expiries)

    return _PartitionChanges(ensured=ensured, dropped=dropped, alerts=alerts)


def _tune_partition_autovacuum(conn: psycopg.Connection, partition_name: str, errors: list[str]) -> None:
    row = conn.execute("SELECT reloptions FROM pg_class WHERE oid = %s::regclass", [partition_name]).fetchone()
    current = set(row[0] or []) if row else set()
    if current.issuperset(_PARTITION_AUTOVACUUM_OPTIONS):
        return
    # ALTER takes a lock that conflicts with a running autovacuum, so skip it when the options
    # are already set, and give up quickly rather than queue behind one.
    try:
        conn.execute("SET lock_timeout = '5s'")
        conn.execute(f"ALTER TABLE {partition_name} SET ({', '.join(_PARTITION_AUTOVACUUM_OPTIONS)})")
    except Exception as e:
        errors.append(f"Failed to tune autovacuum on {partition_name}: {e}")
        logger.exception("Failed to tune partition autovacuum", partition=partition_name)
    finally:
        conn.execute("RESET lock_timeout")


def _partition_ddl_database_url() -> str:
    # Only the owner of a partitioned table can create its partitions, and the migration role owns the queue tables.
    return settings.WAREHOUSE_SOURCES_QUEUE_PARTITION_DATABASE_URL or settings.WAREHOUSE_SOURCES_DATABASE_URL


def _list_partitions(conn: psycopg.Connection, table: str) -> list[str]:
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


def _partition_date(partition_name: str) -> date | None:
    suffix = partition_name.rsplit("_", 1)[-1]
    try:
        return date(int(suffix[:4]), int(suffix[4:6]), int(suffix[6:8]))
    except (ValueError, IndexError):
        return None


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
) -> bool:
    """Apply retention to rows in the default partition, and return whether it finished.

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
        return False
    if deleted:
        logger.warning("Expired old default partition rows", partition=partition_name, deleted=deleted)
    return True


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


def _find_partition_alerts(conn: psycopg.Connection, today: date, failed_default_expiries: set[str]) -> list[str]:
    """Return one Slack message for each problem that needs someone to act.

    A missing partition for today does not alert. After rows for today land in the default
    partition, Postgres refuses to create today's partition, and retention deletes those rows
    later. A cause that also blocks tomorrow's partition still alerts through the upcoming check.
    """
    # The newest partition is the only one a run creates for the first time. Leaving it out gives a
    # failed create one retry before it alerts, like the retention check below.
    upcoming = [today + timedelta(days=offset) for offset in range(1, PARTITIONS_AHEAD - 1)]
    # Data this old was due for removal in at least two daily runs, so one transient failure does not alert.
    stuck_before = today - timedelta(days=RETENTION_DAYS + 1)
    stuck_before_at = datetime.combine(stuck_before, datetime.min.time(), tzinfo=UTC)
    missing: dict[str, list[date]] = {}
    stuck: list[str] = []
    for table in PARTITIONED_TABLES:
        existing: set[date] = set()
        for partition_name in _list_partitions(conn, table):
            if partition_name.endswith("_default"):
                # A finished expiry leaves no row this old, so scan the partition only when this run's expiry
                # failed. The scan has no created_at index to use, and a default partition can hold days of rows.
                if partition_name in failed_default_expiries:
                    row = conn.execute(
                        f"SELECT EXISTS (SELECT 1 FROM {partition_name} WHERE created_at < %s)", [stuck_before_at]
                    ).fetchone()
                    if row and row[0]:
                        stuck.append(f"• `{partition_name}`: rows created before {stuck_before.isoformat()}")
                continue
            partition_date = _partition_date(partition_name)
            if partition_date is not None:
                existing.add(partition_date)
        if table_missing := [d for d in upcoming if d not in existing]:
            missing[table] = table_missing
        if table_stuck := sorted(d for d in existing if d < stuck_before):
            stuck.append(f"• `{table}`: oldest {table_stuck[0].isoformat()} ({len(table_stuck)} in total)")

    alerts: list[str] = []
    if missing:
        first_missing = min(dates[0] for dates in missing.values())
        lines = "\n".join(f"• `{table}`: {', '.join(d.isoformat() for d in dates)}" for table, dates in missing.items())
        alerts.append(
            f"*Upcoming partitions are missing.* From {first_missing.isoformat()} 00:00 UTC, new rows land in "
            f"the default partition. Once that happens, Postgres can't create the partition for that day.\n{lines}\n"
            "Find the cause in the worker logs under `Failed to create partition`. Check that "
            "`WAREHOUSE_SOURCES_QUEUE_PARTITION_DATABASE_URL` logs in as the role that owns the queue tables, "
            f"then trigger the `{SCHEDULE_ID}` schedule."
        )
    if stuck:
        lines = "\n".join(stuck)
        alerts.append(
            f"*Retention is stuck.* This data should have been removed at least a day ago:\n{lines}\n"
            "Find the cause in the worker logs under `Failed to drop partition`, "
            "`Failed to terminalize stranded runs`, or `Failed to expire old default partition rows`."
        )
    return alerts


def _send_slack_alert(alerts: list[str]) -> None:
    webhook_url = settings.WAREHOUSE_SOURCES_QUEUE_PARTITION_SLACK_WEBHOOK_URL
    if not webhook_url:
        logger.warning("No Slack webhook configured for partition management alerts")
        return

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":rotating_light: *Warehouse sources queue partitions need attention*",
            },
        },
        *({"type": "section", "text": {"type": "mrkdwn", "text": alert}} for alert in alerts),
    ]

    try:
        response = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to send Slack notification", error=str(e))
