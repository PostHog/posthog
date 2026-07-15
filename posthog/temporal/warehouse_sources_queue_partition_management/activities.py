from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from django.conf import settings

import psycopg
import requests
import structlog
import temporalio.activity

logger = structlog.get_logger(__name__)

BATCH_TABLE = "sourcebatch"
PARTITIONED_TABLES = [BATCH_TABLE, "sourcebatchstatus", "sourcebatchduckgresstatus"]
PARTITIONS_AHEAD = 7
RETENTION_DAYS = 7

# Batch states that still represent unloaded work. Dropping a partition (and its
# S3 extraction payloads) while any of these remain destroys the data with no way
# back — and every signal tracking it (freshness gauge, CDC backpressure guard)
# quietly resets, so the loss would be silent. Mirrors SourceBatch.LatestState.
NON_TERMINAL_BATCH_STATES = ("pending", "waiting", "executing", "waiting_retry")

# The duckgres apply-marker table is unpartitioned (small rows, UNIQUE-constrained),
# so retention is DELETE-based. Must comfortably exceed the consumers' eligibility
# window (PARTITION_PRUNING_INTERVAL, 14d): the duckgres ordering gate and
# has_applied idempotency read apply rows for everything still eligible.
DUCKGRES_APPLY_TABLE = "sourcebatchduckgresapply"
DUCKGRES_APPLY_RETENTION_DAYS = 30


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
        # A live batch's newest status can't sit in a partition older than the batch
        # itself, so blocking the batch's date across all three tables (and the S3
        # prefixes) preserves everything retention would otherwise destroy.
        blocked_dates = _dates_with_non_terminal_batches(conn, cutoff, errors)
        if blocked_dates:
            for blocked in sorted(blocked_dates):
                errors.append(
                    f"Refusing to drop {blocked.isoformat()} partitions: non-terminal batches would be "
                    f"destroyed along with their S3 payloads. Recover or fail the stuck runs "
                    f"(manage_warehouse_queue), after which retention resumes."
                )
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
                    continue
                suffix = partition_name.rsplit("_", 1)[-1]
                try:
                    partition_date = date(int(suffix[:4]), int(suffix[4:6]), int(suffix[6:8]))
                except (ValueError, IndexError):
                    continue
                if partition_date < cutoff:
                    if blocked_dates is None or partition_date in blocked_dates:
                        continue
                    try:
                        conn.execute(f"DROP TABLE IF EXISTS {partition_name}")
                        dropped.append(partition_name)
                    except Exception as e:
                        errors.append(f"Failed to drop {partition_name}: {e}")
                        logger.exception("Failed to drop partition", partition=partition_name)

        _verify_partitions(conn, today, errors)

        try:
            cursor = conn.execute(
                f"DELETE FROM {DUCKGRES_APPLY_TABLE} "
                f"WHERE created_at < now() - interval '{DUCKGRES_APPLY_RETENTION_DAYS} days'"
            )
            if cursor.rowcount:
                logger.info("duckgres_apply_markers_pruned", count=cursor.rowcount)
        except Exception as e:
            errors.append(f"Failed to prune {DUCKGRES_APPLY_TABLE}: {e}")
            logger.exception("Failed to prune duckgres apply markers")

    s3_deleted = _cleanup_old_s3_extractions(today, errors, blocked_dates=blocked_dates)

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


def _dates_with_non_terminal_batches(
    conn: psycopg.Connection,
    cutoff: date,
    errors: list[str],
) -> set[date] | None:
    """Partition dates before ``cutoff`` whose batches still hold unloaded work.

    Returns None when the probe itself fails — callers must then skip every
    retention delete this run. Fail-safe: an extra day of retention is
    recoverable, destroyed batch rows and S3 payloads are not.
    """
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT created_at::date
            FROM {BATCH_TABLE}
            WHERE created_at < %s
              AND latest_state = ANY(%s)
            """,
            [cutoff, list(NON_TERMINAL_BATCH_STATES)],
        ).fetchall()
    except Exception as e:
        errors.append(f"Failed to probe for non-terminal batches; skipping all retention deletes this run: {e}")
        logger.exception("Failed to probe for non-terminal batches before retention")
        return None
    return {row[0] for row in rows}


def _cleanup_old_s3_extractions(
    today: date,
    errors: list[str],
    blocked_dates: AbstractSet[date] | None = frozenset(),
) -> list[str]:
    """Delete S3 date-partitioned extraction prefixes older than RETENTION_DAYS.

    ``blocked_dates`` holds dates whose batches are still non-terminal — their
    payloads must survive until the work resolves. None means the probe failed,
    so nothing is deleted this run.
    """
    from products.data_warehouse.backend.facade.api import get_s3_client

    deleted: list[str] = []
    if blocked_dates is None:
        return deleted

    s3 = get_s3_client()
    base_prefix = f"{settings.DATAWAREHOUSE_BUCKET}/data_pipelines_extract"
    cutoff = today - timedelta(days=RETENTION_DAYS)

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
        if partition_date < cutoff and partition_date not in blocked_dates:
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
