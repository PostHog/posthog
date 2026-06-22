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

# Shared CTE prelude for eligibility queries (note the trailing comma — callers
# append their own CTEs/SELECT). Expects a %(team_ids)s bigint[] parameter
# (NULL = no team filter).
#
# - run_starts: per-run start time, the total order used for cross-run gating
#   (run_uuid tiebreak makes it total even for identical timestamps).
# - failed_runs: runs terminally excluded from the sink — Delta-failed or
#   Duckgres-failed (including superseded).
# - incomplete_runs: non-failed runs that still owe unapplied data batches;
#   these block newer runs of the same schema (cross-run head-of-line).
ELIGIBILITY_CTES = f"""run_starts AS MATERIALIZED (
                    SELECT b_rs.run_uuid, min(b_rs.created_at) AS started_at
                    FROM {BATCH_TABLE} b_rs
                    WHERE b_rs.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR b_rs.team_id = ANY(%(team_ids)s))
                    GROUP BY b_rs.run_uuid
                ),
                failed_runs AS MATERIALIZED (
                    SELECT DISTINCT b2.run_uuid
                    FROM {BATCH_TABLE} b2
                    JOIN {DELTA_STATUS_VIEW} ds2 ON b2.id = ds2.batch_id
                    WHERE b2.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR b2.team_id = ANY(%(team_ids)s))
                        AND ds2.job_state = 'failed'
                    UNION
                    SELECT DISTINCT b3.run_uuid
                    FROM {BATCH_TABLE} b3
                    JOIN {DUCKGRES_STATUS_VIEW} dgs3 ON b3.id = dgs3.batch_id
                    WHERE b3.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR b3.team_id = ANY(%(team_ids)s))
                        AND dgs3.job_state = 'failed'
                ),
                incomplete_runs AS MATERIALIZED (
                    SELECT old.team_id, old.schema_id, old.run_uuid, rs_ir.started_at
                    FROM {BATCH_TABLE} old
                    JOIN {DELTA_STATUS_VIEW} ods ON old.id = ods.batch_id
                    JOIN run_starts rs_ir ON rs_ir.run_uuid = old.run_uuid
                    LEFT JOIN {DUCKGRES_APPLY_TABLE} oa
                        ON oa.team_id = old.team_id
                        AND oa.schema_id = old.schema_id
                        AND oa.run_uuid = old.run_uuid
                        AND oa.batch_index = old.batch_index
                    WHERE old.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR old.team_id = ANY(%(team_ids)s))
                        AND ods.job_state = 'succeeded'
                        AND old.is_final_batch = false
                        AND oa.id IS NULL
                        AND old.run_uuid NOT IN (SELECT run_uuid FROM failed_runs)
                    GROUP BY old.team_id, old.schema_id, old.run_uuid, rs_ir.started_at
                ),"""


class DuckgresBatchQueue:
    @staticmethod
    async def get_delta_succeeded_and_lock(
        conn: psycopg.AsyncConnection[Any],
        *,
        limit: int = 50,
        retry_backoff_base_seconds: int = 0,
        team_ids: list[int] | None = None,
    ) -> list[PendingBatch]:
        """Fetch Duckgres-eligible batches whose Delta load has succeeded.

        Duckgres has its own sink state. A source batch is eligible only after the
        Delta consumer marks that exact batch row as succeeded.

        ``retry_backoff_base_seconds`` gates the ``waiting_retry`` branch on the age
        of the latest Duckgres status row, mirroring the Delta queue's backoff.

        ``team_ids`` restricts eligibility to duckgres-enabled teams (None = no
        filter, for tests/dev). The sink must never claim batches for orgs without
        a Duckgres deployment — they would burn retries and fail runs for nothing.

        Cross-run head-of-line: a batch is ineligible while an older run (by run
        start time) of the same (team_id, schema_id) still has unapplied,
        non-failed data batches. Without this, a newer run's batch-0
        CREATE OR REPLACE could interleave with an older run's remaining
        inserts/merges and permanently mix two runs' rows in the Duckgres table.
        Liveness: older runs either complete, fail (max attempts), or are
        superseded by ``supersede_replaced_runs`` — all three unblock the gate.
        """
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                WITH {ELIGIBILITY_CTES}
                candidates AS MATERIALIZED (
                    SELECT
                        {pending_batch_select_columns("dgs")}
                    FROM {BATCH_TABLE} b
                    JOIN {DELTA_STATUS_VIEW} ds ON b.id = ds.batch_id
                    JOIN run_starts rs_b ON rs_b.run_uuid = b.run_uuid
                    LEFT JOIN {DUCKGRES_STATUS_VIEW} dgs ON b.id = dgs.batch_id
                    WHERE
                        b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR b.team_id = ANY(%(team_ids)s))
                        AND ds.job_state = 'succeeded'
                        AND (
                            dgs.batch_id IS NULL
                            OR (
                                dgs.job_state = 'waiting_retry'
                                AND dgs.created_at <= now() - make_interval(
                                    secs => %(backoff)s * GREATEST(COALESCE(dgs.attempt, 1), 1)
                                )
                            )
                        )
                        AND (
                            -- Self-apply exclusion, scoped to statusless batches: an
                            -- applied batch with no duckgres status row must not be
                            -- re-claimed. A batch stranded in waiting_retry AFTER its
                            -- apply marker landed (crash between mark_applied and the
                            -- 'succeeded' write) stays claimable on purpose: its no-op
                            -- pass converges the status to 'succeeded'.
                            b.is_final_batch = true
                            OR dgs.batch_id IS NOT NULL
                            OR NOT EXISTS (
                                SELECT 1
                                FROM {DUCKGRES_APPLY_TABLE} current_apply
                                WHERE current_apply.team_id = b.team_id
                                    AND current_apply.schema_id = b.schema_id
                                    AND current_apply.run_uuid = b.run_uuid
                                    AND current_apply.batch_index = b.batch_index
                            )
                        )
                        AND b.run_uuid NOT IN (SELECT run_uuid FROM failed_runs)
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
                        AND NOT EXISTS (
                            -- Cross-run head-of-line: an older non-failed run of this
                            -- schema still has unapplied data batches.
                            SELECT 1
                            FROM incomplete_runs ir
                            WHERE ir.team_id = b.team_id
                                AND ir.schema_id = b.schema_id
                                AND ir.run_uuid <> b.run_uuid
                                AND (ir.started_at, ir.run_uuid) < (rs_b.started_at, b.run_uuid)
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
                {"limit": limit, "backoff": retry_backoff_base_seconds, "team_ids": team_ids},
            )
            rows = await cur.fetchall()
        return [PendingBatch(**row) for row in rows]

    @staticmethod
    async def supersede_replaced_runs(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_ids: list[int] | None = None,
    ) -> int:
        """Fail older runs' pending duckgres work once a newer replace-run is ready.

        When a newer run whose batch 0 will CREATE OR REPLACE the table (full
        refresh, or first-ever incremental) is delta-succeeded and not yet
        applied, any older run's remaining unapplied duckgres work is worthless —
        applying it after the replace would mix stale rows into the new table.
        Mark those batches 'failed' (reason: superseded) so the failed-run
        exclusion retires them and the cross-run gate opens for the new run.

        Skips batches currently 'executing' (their attempt resolves on its own)
        and anything already terminal. Returns the number of batches superseded.
        """
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                WITH {ELIGIBILITY_CTES}
                replace_heads AS MATERIALIZED (
                    SELECT nb.team_id, nb.schema_id, nb.run_uuid, rs.started_at
                    FROM {BATCH_TABLE} nb
                    JOIN {DELTA_STATUS_VIEW} nds ON nb.id = nds.batch_id
                    JOIN run_starts rs ON rs.run_uuid = nb.run_uuid
                    LEFT JOIN {DUCKGRES_APPLY_TABLE} na
                        ON na.team_id = nb.team_id
                        AND na.schema_id = nb.schema_id
                        AND na.run_uuid = nb.run_uuid
                        AND na.batch_index = nb.batch_index
                    WHERE nb.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR nb.team_id = ANY(%(team_ids)s))
                        AND nds.job_state = 'succeeded'
                        AND nb.batch_index = 0
                        AND nb.is_final_batch = false
                        AND nb.is_resume = false
                        AND (
                            nb.sync_type = 'full_refresh'
                            OR (nb.sync_type = 'incremental' AND nb.is_first_ever_sync)
                        )
                        AND na.id IS NULL
                        AND nb.run_uuid NOT IN (SELECT run_uuid FROM failed_runs)
                ),
                victims AS (
                    SELECT DISTINCT ON (old.id) old.id AS batch_id, rh.run_uuid AS superseded_by
                    FROM {BATCH_TABLE} old
                    JOIN replace_heads rh
                        ON rh.team_id = old.team_id AND rh.schema_id = old.schema_id
                    JOIN run_starts ors ON ors.run_uuid = old.run_uuid
                    JOIN {DELTA_STATUS_VIEW} ods ON old.id = ods.batch_id
                    LEFT JOIN {DUCKGRES_STATUS_VIEW} odgs ON old.id = odgs.batch_id
                    LEFT JOIN {DUCKGRES_APPLY_TABLE} oa
                        ON oa.team_id = old.team_id
                        AND oa.schema_id = old.schema_id
                        AND oa.run_uuid = old.run_uuid
                        AND oa.batch_index = old.batch_index
                    WHERE old.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND old.run_uuid <> rh.run_uuid
                        AND (ors.started_at, old.run_uuid) < (rh.started_at, rh.run_uuid)
                        AND ods.job_state = 'succeeded'
                        AND old.run_uuid NOT IN (SELECT run_uuid FROM failed_runs)
                        AND (old.is_final_batch = true OR oa.id IS NULL)
                        AND (odgs.batch_id IS NULL OR odgs.job_state = 'waiting_retry')
                    ORDER BY old.id, rh.started_at DESC, rh.run_uuid DESC
                )
                INSERT INTO {DUCKGRES_STATUS_TABLE} (batch_id, job_state, attempt, error_response)
                SELECT
                    v.batch_id,
                    'failed',
                    0,
                    jsonb_build_object('error', 'superseded by newer replace run ' || v.superseded_by)
                FROM victims v
                """,
                {"team_ids": team_ids},
            )
            return cur.rowcount or 0

    @staticmethod
    async def get_backlog_stats(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_ids: list[int] | None = None,
    ) -> tuple[int, float | None]:
        """(count, oldest age seconds) of delta-succeeded, unapplied, non-failed data batches.

        This is the sink's lag signal: both silent-loss modes (7-day queue
        retention, permanently failed runs) are time-bounded, so alerting needs
        the age of the oldest batch the sink still owes.
        """
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                WITH {ELIGIBILITY_CTES}
                backlog AS (
                    SELECT b.created_at
                    FROM {BATCH_TABLE} b
                    JOIN {DELTA_STATUS_VIEW} ds ON b.id = ds.batch_id
                    LEFT JOIN {DUCKGRES_APPLY_TABLE} a
                        ON a.team_id = b.team_id
                        AND a.schema_id = b.schema_id
                        AND a.run_uuid = b.run_uuid
                        AND a.batch_index = b.batch_index
                    WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR b.team_id = ANY(%(team_ids)s))
                        AND ds.job_state = 'succeeded'
                        AND b.is_final_batch = false
                        AND a.id IS NULL
                        AND b.run_uuid NOT IN (SELECT run_uuid FROM failed_runs)
                )
                SELECT count(*), EXTRACT(EPOCH FROM now() - min(created_at))
                FROM backlog
                """,
                {"team_ids": team_ids},
            )
            row = await cur.fetchone()
        count = int(row[0]) if row else 0
        oldest_age = float(row[1]) if row and row[1] is not None else None
        return count, oldest_age

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
    async def get_stale_executing(
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int = 0,
    ) -> list[PendingBatch]:
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
                        AND dgs.created_at <= now() - make_interval(secs => %(grace)s)
                    ORDER BY b.created_at ASC, b.batch_index ASC
                )
                SELECT c.*
                FROM candidates c
                WHERE pg_try_advisory_lock(
                    {DUCKGRES_ADVISORY_LOCK_NAMESPACE},
                    hashtext(c.team_id::text || ':' || c.schema_id)
                )
                ORDER BY c.created_at ASC, c.batch_index ASC
                """,
                {"grace": grace_seconds},
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
