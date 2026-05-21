from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings

import psycopg
import requests
import structlog
import temporalio.activity

logger = structlog.get_logger(__name__)

PARTITIONED_TABLES = ["sourcebatch", "sourcebatchstatus"]
PARTITIONS_AHEAD = 7
RETENTION_DAYS = 7


@dataclass(frozen=True, slots=True)
class PartitionResult:
    ensured: list[str]
    dropped: list[str]
    errors: list[str]

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
        today = date.today()

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
                    continue
                suffix = partition_name.rsplit("_", 1)[-1]
                try:
                    partition_date = date(int(suffix[:4]), int(suffix[4:6]), int(suffix[6:8]))
                except (ValueError, IndexError):
                    continue
                if partition_date < cutoff:
                    try:
                        conn.execute(f"DROP TABLE IF EXISTS {partition_name}")
                        dropped.append(partition_name)
                    except Exception as e:
                        errors.append(f"Failed to drop {partition_name}: {e}")
                        logger.exception("Failed to drop partition", partition=partition_name)

        _verify_partitions(conn, today, errors)

    result = PartitionResult(ensured=ensured, dropped=dropped, errors=errors)

    logger.info(
        "Partition management completed",
        ensured_count=len(ensured),
        dropped_count=len(dropped),
        error_count=len(errors),
        success=result.success,
    )

    if not result.success:
        _send_slack_failure(errors)

    return {"ensured": result.ensured, "dropped": result.dropped, "errors": result.errors, "success": result.success}


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
