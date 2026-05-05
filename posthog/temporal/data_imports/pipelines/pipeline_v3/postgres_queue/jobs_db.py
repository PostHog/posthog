"""
Postgres-based job queue for warehouse source batch processing.

Replaces the Kafka topic `warehouse_sources_jobs` with direct Postgres inserts
and advisory-lock-based coordination. All SQL is isolated here so that the
producer (Temporal activity) and consumer share a single interface to the queue.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

BATCH_TABLE = "sourcebatch"
STATUS_TABLE = "sourcebatchstatus"
STATUS_VIEW = "v_latest_source_batch_status"

# Namespace for advisory locks to avoid collisions with other PostHog subsystems.
ADVISORY_LOCK_NAMESPACE = 0x57485300  # "WHS\0" in hex

# Partition pruning hint: only scan partitions within this window.
# Set to 2x the retention period so the planner can skip dropped
# partitions. Not a correctness filter — older partitions are already
# gone by the time this matters.
PARTITION_PRUNING_INTERVAL = "14 days"


@dataclass(frozen=True, slots=True)
class PendingBatch:
    """A batch row fetched from the queue, ready to be processed by the consumer."""

    id: str
    team_id: int
    schema_id: str
    source_id: str
    job_id: str
    run_uuid: str
    batch_index: int
    s3_path: str
    row_count: int
    byte_size: int
    is_final_batch: bool
    total_batches: int | None
    total_rows: int | None
    sync_type: str
    cumulative_row_count: int
    resource_name: str
    is_resume: bool
    is_first_ever_sync: bool
    metadata: dict[str, Any]
    latest_attempt: int
    created_at: datetime | None = None

    def to_export_signal(self) -> dict[str, Any]:
        """Temporary bridge: convert a PendingBatch into an ExportSignalMessage dict
        so we can reuse the existing process_message() for local testing. The final
        solution will operate on PendingBatch directly without this conversion."""
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
            "schema_id": self.schema_id,
            "source_id": self.source_id,
            "resource_name": self.resource_name,
            "run_uuid": self.run_uuid,
            "batch_index": self.batch_index,
            "s3_path": self.s3_path,
            "row_count": self.row_count,
            "byte_size": self.byte_size,
            "is_final_batch": self.is_final_batch,
            "total_batches": self.total_batches,
            "total_rows": self.total_rows,
            "sync_type": self.sync_type,
            "cumulative_row_count": self.cumulative_row_count,
            "is_resume": self.is_resume,
            "is_first_ever_sync": self.is_first_ever_sync,
            "timestamp_ns": self.metadata.get("timestamp_ns", time.time_ns()),
            "data_folder": self.metadata.get("data_folder"),
            "schema_path": self.metadata.get("schema_path"),
            "primary_keys": self.metadata.get("primary_keys"),
            "partition_count": self.metadata.get("partition_count"),
            "partition_size": self.metadata.get("partition_size"),
            "partition_keys": self.metadata.get("partition_keys"),
            "partition_format": self.metadata.get("partition_format"),
            "partition_mode": self.metadata.get("partition_mode"),
            "cdc_write_mode": self.metadata.get("cdc_write_mode"),
            "cdc_table_mode": self.metadata.get("cdc_table_mode"),
        }


class BatchQueue:
    """
    Async interface to the Postgres batch queue tables. Each method runs
    its own query against the provided connection — callers manage connections
    and transactions.
    """

    # -- writes (producer side) ------------------------------------------------

    @staticmethod
    async def insert(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        source_id: str,
        job_id: str,
        run_uuid: str,
        batch_index: int,
        s3_path: str,
        row_count: int,
        byte_size: int,
        is_final_batch: bool,
        total_batches: int | None,
        total_rows: int | None,
        sync_type: str,
        cumulative_row_count: int,
        resource_name: str,
        is_resume: bool,
        is_first_ever_sync: bool,
        metadata: dict[str, Any],
    ) -> str:
        """Insert a batch row into the queue. Returns the new batch id."""
        row = await conn.execute(
            f"""
            INSERT INTO {BATCH_TABLE} (
                id, team_id, schema_id, source_id, job_id, run_uuid,
                batch_index, s3_path, row_count, byte_size, is_final_batch,
                total_batches, total_rows, sync_type, cumulative_row_count,
                resource_name, is_resume, is_first_ever_sync, metadata, created_at
            ) VALUES (
                gen_random_uuid(),
                %(team_id)s, %(schema_id)s, %(source_id)s, %(job_id)s, %(run_uuid)s,
                %(batch_index)s, %(s3_path)s, %(row_count)s, %(byte_size)s, %(is_final_batch)s,
                %(total_batches)s, %(total_rows)s, %(sync_type)s, %(cumulative_row_count)s,
                %(resource_name)s, %(is_resume)s, %(is_first_ever_sync)s, %(metadata)s, now()
            )
            RETURNING id
            """,
            {
                "team_id": team_id,
                "schema_id": schema_id,
                "source_id": source_id,
                "job_id": job_id,
                "run_uuid": run_uuid,
                "batch_index": batch_index,
                "s3_path": s3_path,
                "row_count": row_count,
                "byte_size": byte_size,
                "is_final_batch": is_final_batch,
                "total_batches": total_batches,
                "total_rows": total_rows,
                "sync_type": sync_type,
                "cumulative_row_count": cumulative_row_count,
                "resource_name": resource_name,
                "is_resume": is_resume,
                "is_first_ever_sync": is_first_ever_sync,
                "metadata": json.dumps(metadata),
            },
        )
        batch_id: str = str((await row.fetchone())[0])  # type: ignore[index]
        return batch_id

    # -- reads (consumer side) -------------------------------------------------

    @staticmethod
    async def get_unprocessed_and_lock(
        conn: psycopg.AsyncConnection[Any],
        *,
        limit: int = 50,
    ) -> list[PendingBatch]:
        """Fetch unprocessed batches whose (team_id, schema_id) advisory lock is acquirable.

        Uses a MATERIALIZED CTE so that candidate selection (with LIMIT) is
        fully resolved before any advisory lock is acquired.  Without this,
        Postgres is free to evaluate pg_try_advisory_lock on rows that are
        later discarded by other predicates or by LIMIT, creating phantom
        locks that unlock_for_batches never releases.
        """
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                WITH candidates AS MATERIALIZED (
                    SELECT
                        b.id, b.team_id, b.schema_id, b.source_id, b.job_id,
                        b.run_uuid, b.batch_index, b.s3_path, b.row_count, b.byte_size,
                        b.is_final_batch, b.total_batches, b.total_rows, b.sync_type,
                        b.cumulative_row_count, b.resource_name, b.is_resume,
                        b.is_first_ever_sync, b.metadata,
                        COALESCE(s.attempt, 0) AS latest_attempt,
                        b.created_at
                    FROM {BATCH_TABLE} b
                    LEFT JOIN {STATUS_VIEW} s ON b.id = s.batch_id
                    WHERE
                        b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (s.batch_id IS NULL OR s.job_state = 'waiting_retry')
                        AND b.run_uuid NOT IN (
                            SELECT DISTINCT b2.run_uuid
                            FROM {BATCH_TABLE} b2
                            JOIN {STATUS_VIEW} s2 ON b2.id = s2.batch_id
                            WHERE b2.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                                AND s2.job_state = 'failed'
                        )
                    ORDER BY b.created_at ASC, b.batch_index ASC
                    LIMIT %(limit)s
                )
                SELECT c.*
                FROM candidates c
                WHERE pg_try_advisory_lock({ADVISORY_LOCK_NAMESPACE}, hashtext(c.team_id::text || ':' || c.schema_id))
                ORDER BY c.created_at ASC, c.batch_index ASC
                """,
                {"limit": limit},
            )
            rows = await cur.fetchall()
        return [PendingBatch(**row) for row in rows]

    @staticmethod
    async def update_status(
        conn: psycopg.AsyncConnection[Any],
        *,
        batch_id: str,
        job_state: str,
        attempt: int = 0,
        error_response: dict[str, Any] | None = None,
    ) -> None:
        """Append a status row for a batch (executing, succeeded, waiting_retry, failed)."""
        await conn.execute(
            f"""
            INSERT INTO {STATUS_TABLE} (batch_id, job_state, attempt, exec_time, error_response, created_at)
            VALUES (%(batch_id)s, %(job_state)s, %(attempt)s, now(), %(error_response)s, now())
            """,
            {
                "batch_id": batch_id,
                "job_state": job_state,
                "attempt": attempt,
                "error_response": json.dumps(error_response) if error_response else None,
            },
        )

    @staticmethod
    async def get_stale_executing(
        conn: psycopg.AsyncConnection[Any],
    ) -> list[PendingBatch]:
        """Find batches stuck in 'executing' whose advisory lock is not held (previous pod crashed).

        Uses a MATERIALIZED CTE for the same reason as get_unprocessed_and_lock:
        candidate rows are fully resolved before any advisory lock is probed.
        """
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                WITH candidates AS MATERIALIZED (
                    SELECT
                        b.id, b.team_id, b.schema_id, b.source_id, b.job_id,
                        b.run_uuid, b.batch_index, b.s3_path, b.row_count, b.byte_size,
                        b.is_final_batch, b.total_batches, b.total_rows, b.sync_type,
                        b.cumulative_row_count, b.resource_name, b.is_resume,
                        b.is_first_ever_sync, b.metadata,
                        COALESCE(s.attempt, 0) AS latest_attempt,
                        b.created_at
                    FROM {BATCH_TABLE} b
                    JOIN {STATUS_VIEW} s ON b.id = s.batch_id
                    WHERE
                        b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND s.job_state = 'executing'
                    ORDER BY b.created_at ASC, b.batch_index ASC
                )
                SELECT c.*
                FROM candidates c
                WHERE pg_try_advisory_lock({ADVISORY_LOCK_NAMESPACE}, hashtext(c.team_id::text || ':' || c.schema_id))
                ORDER BY c.created_at ASC, c.batch_index ASC
                """,
            )
            rows = await cur.fetchall()

        result = [PendingBatch(**row) for row in rows]

        # Release the locks immediately — we only needed them to detect orphans.
        await BatchQueue.unlock_for_batches(conn, batches=result)

        return result

    @staticmethod
    async def fail_run(
        conn: psycopg.AsyncConnection[Any],
        *,
        run_uuid: str,
        reason: str,
    ) -> int:
        """Mark every pending batch in a run as failed. Returns the count of batches failed."""
        cursor = await conn.execute(
            f"""
            INSERT INTO {STATUS_TABLE} (batch_id, job_state, attempt, exec_time, error_response, created_at)
            SELECT b.id, 'failed', 0, now(), %(error_response)s, now()
            FROM {BATCH_TABLE} b
            LEFT JOIN {STATUS_VIEW} s ON b.id = s.batch_id
            WHERE
                b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                AND b.run_uuid = %(run_uuid)s
                AND (s.batch_id IS NULL OR s.job_state IN ('waiting', 'waiting_retry', 'executing'))
            """,
            {
                "run_uuid": run_uuid,
                "error_response": json.dumps({"error": reason}),
            },
        )
        return cursor.rowcount or 0

    @staticmethod
    async def unlock_for_batches(
        conn: psycopg.AsyncConnection[Any],
        *,
        batches: list[PendingBatch],
    ) -> None:
        """Release advisory locks once per returned batch row.

        The MATERIALIZED CTE in get_unprocessed_and_lock ensures locks are
        only acquired on rows that actually appear in the result set, so
        one unlock per row balances the depth exactly.
        """
        for batch in batches:
            await conn.execute(
                "SELECT pg_advisory_unlock(%(ns)s, hashtext(%(key)s))",
                {"ns": ADVISORY_LOCK_NAMESPACE, "key": f"{batch.team_id}:{batch.schema_id}"},
            )
