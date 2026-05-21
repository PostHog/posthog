from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.rows import dict_row

from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    PARTITION_PRUNING_INTERVAL,
    STATUS_VIEW as DELTA_STATUS_VIEW,
    PendingBatch,
    pending_batch_select_columns,
    unlock_advisory_locks,
)

DUCKGRES_STATUS_TABLE = "sourcebatchduckgresstatus"
DUCKGRES_STATUS_VIEW = "v_latest_source_batch_duckgres_status"
DUCKGRES_APPLY_TABLE = "sourcebatchduckgresapply"

DUCKGRES_ADVISORY_LOCK_NAMESPACE = 0x44475300  # "DGS\0" in hex


class DuckgresBatchQueue:
    @staticmethod
    async def get_delta_succeeded_and_lock(
        conn: psycopg.AsyncConnection[Any],
        *,
        limit: int = 50,
    ) -> list[PendingBatch]:
        """Fetch Duckgres-eligible batches whose Delta load has succeeded.

        Duckgres has its own sink state. A source batch is eligible only after the
        Delta consumer marks that exact batch row as succeeded.
        """
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                WITH candidates AS MATERIALIZED (
                    SELECT
                        {pending_batch_select_columns("dgs")}
                    FROM {BATCH_TABLE} b
                    JOIN {DELTA_STATUS_VIEW} ds ON b.id = ds.batch_id
                    LEFT JOIN {DUCKGRES_STATUS_VIEW} dgs ON b.id = dgs.batch_id
                    WHERE
                        b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND ds.job_state = 'succeeded'
                        AND (dgs.batch_id IS NULL OR dgs.job_state = 'waiting_retry')
                        AND (
                            b.is_final_batch = true
                            OR NOT EXISTS (
                                SELECT 1
                                FROM {DUCKGRES_APPLY_TABLE} current_apply
                                WHERE current_apply.team_id = b.team_id
                                    AND current_apply.schema_id = b.schema_id
                                    AND current_apply.run_uuid = b.run_uuid
                                    AND current_apply.batch_index = b.batch_index
                            )
                        )
                        AND b.run_uuid NOT IN (
                            SELECT DISTINCT b2.run_uuid
                            FROM {BATCH_TABLE} b2
                            JOIN {DELTA_STATUS_VIEW} ds2 ON b2.id = ds2.batch_id
                            WHERE b2.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                                AND ds2.job_state = 'failed'
                        )
                        AND b.run_uuid NOT IN (
                            SELECT DISTINCT b3.run_uuid
                            FROM {BATCH_TABLE} b3
                            JOIN {DUCKGRES_STATUS_VIEW} dgs3 ON b3.id = dgs3.batch_id
                            WHERE b3.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                                AND dgs3.job_state = 'failed'
                        )
                        AND NOT EXISTS (
                            SELECT 1
                            FROM {BATCH_TABLE} prev
                            LEFT JOIN {DUCKGRES_APPLY_TABLE} a
                                ON a.team_id = prev.team_id
                                AND a.schema_id = prev.schema_id
                                AND a.run_uuid = prev.run_uuid
                                AND a.batch_index = prev.batch_index
                            WHERE prev.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                                AND prev.team_id = b.team_id
                                AND prev.schema_id = b.schema_id
                                AND prev.run_uuid = b.run_uuid
                                AND prev.is_final_batch = false
                                AND (
                                    prev.batch_index < b.batch_index
                                    OR (b.is_final_batch = true AND prev.batch_index <= b.batch_index)
                                )
                                AND a.id IS NULL
                        )
                    ORDER BY b.created_at ASC, b.batch_index ASC, b.is_final_batch ASC
                    LIMIT %(limit)s
                )
                SELECT c.*
                FROM candidates c
                WHERE pg_try_advisory_lock(
                    {DUCKGRES_ADVISORY_LOCK_NAMESPACE},
                    hashtext(c.team_id::text || ':' || c.schema_id)
                )
                ORDER BY c.created_at ASC, c.batch_index ASC, c.is_final_batch ASC
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
        await conn.execute(
            f"""
            INSERT INTO {DUCKGRES_STATUS_TABLE} (batch_id, job_state, attempt, exec_time, error_response, created_at)
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
    async def mark_applied(
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {DUCKGRES_APPLY_TABLE} (
                team_id, schema_id, run_uuid, batch_index, batch_id, row_count, created_at
            ) VALUES (
                %(team_id)s, %(schema_id)s, %(run_uuid)s, %(batch_index)s, %(batch_id)s, %(row_count)s, now()
            )
            ON CONFLICT (team_id, schema_id, run_uuid, batch_index) DO NOTHING
            """,
            {
                "team_id": batch.team_id,
                "schema_id": batch.schema_id,
                "run_uuid": batch.run_uuid,
                "batch_index": batch.batch_index,
                "batch_id": batch.id,
                "row_count": batch.row_count,
            },
        )

    @staticmethod
    async def has_applied(
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> bool:
        row = await conn.execute(
            f"""
            SELECT 1
            FROM {DUCKGRES_APPLY_TABLE}
            WHERE team_id = %(team_id)s
                AND schema_id = %(schema_id)s
                AND run_uuid = %(run_uuid)s
                AND batch_index = %(batch_index)s
            LIMIT 1
            """,
            {
                "team_id": batch.team_id,
                "schema_id": batch.schema_id,
                "run_uuid": batch.run_uuid,
                "batch_index": batch.batch_index,
            },
        )
        return await row.fetchone() is not None

    @staticmethod
    async def fail_run(
        conn: psycopg.AsyncConnection[Any],
        *,
        run_uuid: str,
        reason: str,
    ) -> int:
        cursor = await conn.execute(
            f"""
            INSERT INTO {DUCKGRES_STATUS_TABLE} (batch_id, job_state, attempt, exec_time, error_response, created_at)
            SELECT b.id, 'failed', 0, now(), %(error_response)s, now()
            FROM {BATCH_TABLE} b
            JOIN {DELTA_STATUS_VIEW} ds ON b.id = ds.batch_id
            LEFT JOIN {DUCKGRES_STATUS_VIEW} dgs ON b.id = dgs.batch_id
            WHERE
                b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                AND b.run_uuid = %(run_uuid)s
                AND ds.job_state = 'succeeded'
                AND (dgs.batch_id IS NULL OR dgs.job_state IN ('waiting_retry', 'executing'))
            """,
            {
                "run_uuid": run_uuid,
                "error_response": json.dumps({"error": reason}),
            },
        )
        return cursor.rowcount or 0

    @staticmethod
    async def get_stale_executing(conn: psycopg.AsyncConnection[Any]) -> list[PendingBatch]:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                WITH candidates AS MATERIALIZED (
                    SELECT
                        {pending_batch_select_columns("dgs")}
                    FROM {BATCH_TABLE} b
                    JOIN {DUCKGRES_STATUS_VIEW} dgs ON b.id = dgs.batch_id
                    WHERE
                        b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND dgs.job_state = 'executing'
                    ORDER BY b.created_at ASC, b.batch_index ASC
                )
                SELECT c.*
                FROM candidates c
                WHERE pg_try_advisory_lock(
                    {DUCKGRES_ADVISORY_LOCK_NAMESPACE},
                    hashtext(c.team_id::text || ':' || c.schema_id)
                )
                ORDER BY c.created_at ASC, c.batch_index ASC
                """
            )
            rows = await cur.fetchall()

        result = [PendingBatch(**row) for row in rows]
        await DuckgresBatchQueue.unlock_for_batches(conn, batches=result)
        return result

    @staticmethod
    async def unlock_for_batches(
        conn: psycopg.AsyncConnection[Any],
        *,
        batches: list[PendingBatch],
    ) -> None:
        await unlock_advisory_locks(conn, batches=batches, namespace=DUCKGRES_ADVISORY_LOCK_NAMESPACE)
