"""Backfill primer for the Duckgres batch sink.

Pre-existing incremental/append schemas have history in Delta that the sink's
per-batch stream will never replay. This module backfills that history with
bounded memory and resume-from-checkpoint, per BACKFILL_SPEC.md:

1. Pin a Delta snapshot and derive a chunk list (~1 GiB of parquet per chunk).
   When the snapshot carries deletion vectors, stream a resolved copy to
   staging first; otherwise the chunks are the Delta table's own live files.
2. Enqueue the chunks as a synthetic "backfill run" in the regular queue,
   pre-marked delta-succeeded (invisible to the Delta consumer, immediately
   eligible for the duckgres fetch).
3. The normal sink consumer applies chunks into ``<table>__backfill``; the
   last chunk atomically swaps it over the live table (processor.py).

The planner below is sync (Django ORM + psycopg + deltalake); the consumer
invokes it from its maintenance tick via sync_to_async.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db.models import Count

import psycopg
import structlog
from prometheus_client import Gauge

from posthog.exceptions_capture import capture_exception
from posthog.models import DuckgresSinkSchemaState
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    PARTITION_PRUNING_INTERVAL,
    STATUS_TABLE as DELTA_STATUS_TABLE,
)

from products.warehouse_sources.backend.models import ExternalDataSchema

logger = structlog.get_logger(__name__)

BACKFILL_JOB_ID = "duckgres-backfill"
CHUNK_TARGET_BYTES = 1024**3  # ~1 GiB of parquet per chunk statement
MAX_CONCURRENT_BACKFILLS_PER_ORG = 1
STAGING_PREFIX = "duckgres_backfill_staging"  # deliberately outside data_pipelines_extract/

BACKFILL_SCHEMAS_GAUGE = Gauge(
    "duckgres_backfill_schemas",
    "Duckgres sink schemas per backfill lifecycle state",
    labelnames=["state"],
    multiprocess_mode="livemax",
)


@dataclass(frozen=True)
class BackfillChunk:
    index: int
    paths: list[str]
    byte_size: int
    row_count: int


def backfill_run_uuid(schema_id: str, snapshot_version: int) -> str:
    return f"{BACKFILL_JOB_ID}-{schema_id}-v{snapshot_version}"


def run_backfill_planner(team_ids: list[int] | None) -> None:
    """One planner pass: bootstrap state rows, plan pending backfills, reconcile.

    Raises nothing: every schema is isolated so one bad table can't stall the
    sweep. Called from the consumer's maintenance tick (sync_to_async).
    """
    if team_ids is not None and not team_ids:
        return

    _bootstrap_state_rows(team_ids)
    _reconcile_backfilling(team_ids)
    _plan_pending(team_ids)
    _emit_state_gauge()


def blocked_schema_ids(team_ids: list[int] | None) -> list[str]:
    """Schemas whose live batches the sink must not apply yet.

    A schema is blocked unless it has a PRIMED state row — including schemas
    with no row at all, so there is no window between flag-flip and the first
    planner pass where a pre-existing schema's live batches sneak through.
    """
    if team_ids is not None and not team_ids:
        return []

    schemas = ExternalDataSchema.objects.exclude(deleted=True)
    if team_ids is not None:
        schemas = schemas.filter(team_id__in=team_ids)
    primed = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkSchemaState.State.PRIMED)
    if team_ids is not None:
        primed = primed.filter(team_id__in=team_ids)
    primed_ids = {str(s) for s in primed.values_list("schema_id", flat=True)}
    return [str(sid) for sid in schemas.values_list("id", flat=True) if str(sid) not in primed_ids]


def _bootstrap_state_rows(team_ids: list[int] | None) -> None:
    """Create state rows for enabled teams' schemas that have none.

    Schemas that need no priming go straight to PRIMED:
    - full_refresh: every run's batch 0 replaces the table completely.
    - schemas without a Delta table yet: their first sync creates everything.
    - cdc: the sink rejects CDC batches outright; do not block the queue on it.
    Everything else (incremental/append with existing history) -> PENDING_BACKFILL.
    """
    schemas = ExternalDataSchema.objects.exclude(deleted=True).select_related("team")
    if team_ids is not None:
        schemas = schemas.filter(team_id__in=team_ids)
    existing = {str(s) for s in DuckgresSinkSchemaState.objects.all().values_list("schema_id", flat=True)}

    to_create: list[DuckgresSinkSchemaState] = []
    for schema in schemas:
        if str(schema.id) in existing:
            continue
        needs_backfill = schema.sync_type not in ("full_refresh", "cdc", None) and schema.table_id is not None
        to_create.append(
            DuckgresSinkSchemaState(
                team_id=schema.team_id,
                schema_id=schema.id,
                state=(
                    DuckgresSinkSchemaState.State.PENDING_BACKFILL
                    if needs_backfill
                    else DuckgresSinkSchemaState.State.PRIMED
                ),
            )
        )
    if to_create:
        DuckgresSinkSchemaState.objects.bulk_create(to_create, ignore_conflicts=True)
        logger.info("duckgres_backfill_bootstrapped", created=len(to_create))


def _plan_pending(team_ids: list[int] | None) -> None:
    pending = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkSchemaState.State.PENDING_BACKFILL)
    if team_ids is not None:
        pending = pending.filter(team_id__in=team_ids)

    for state in pending.select_related("team")[:50]:
        org_id = state.team.organization_id
        busy = (
            DuckgresSinkSchemaState.objects.filter(
                state=DuckgresSinkSchemaState.State.BACKFILLING,
                team__organization_id=org_id,
            ).count()
            >= MAX_CONCURRENT_BACKFILLS_PER_ORG
        )
        if busy:
            continue
        try:
            _plan_one(state)
        except Exception as e:
            logger.exception("duckgres_backfill_plan_failed", schema_id=str(state.schema_id))
            capture_exception(e)
            state.last_error = str(e)[:2000]
            state.save(update_fields=["last_error", "updated_at"])


def _plan_one(state: DuckgresSinkSchemaState) -> None:
    schema = ExternalDataSchema.objects.select_related("source", "team").get(id=state.schema_id)

    snapshot_version, chunks = _resolve_snapshot_chunks(schema)
    if not chunks:
        # Empty Delta table: nothing to prime.
        state.state = DuckgresSinkSchemaState.State.PRIMED
        state.save(update_fields=["state", "updated_at"])
        return

    run_uuid = backfill_run_uuid(str(state.schema_id), snapshot_version)
    inserted = _enqueue_chunks(schema, run_uuid, chunks)

    state.state = DuckgresSinkSchemaState.State.BACKFILLING
    state.snapshot_version = snapshot_version
    state.backfill_run_uuid = run_uuid
    state.chunk_count = len(chunks)
    state.last_error = None
    state.save(
        update_fields=["state", "snapshot_version", "backfill_run_uuid", "chunk_count", "last_error", "updated_at"]
    )
    logger.info(
        "duckgres_backfill_planned",
        schema_id=str(state.schema_id),
        team_id=schema.team_id,
        run_uuid=run_uuid,
        snapshot_version=snapshot_version,
        chunk_count=len(chunks),
        inserted=inserted,
        total_bytes=sum(c.byte_size for c in chunks),
    )


def _reconcile_backfilling(team_ids: list[int] | None) -> None:
    """Progress + terminal-state reconciliation for in-flight backfills.

    - chunks_applied tracked from the queue's apply table.
    - A backfill run superseded by a live full refresh flips straight to
      PRIMED: the superseding replace produces the complete table anyway.
    - Any other failed backfill run keeps BACKFILLING with last_error set
      (alerting surface); operators replan via reset_duckgres_failed_runs.
    """
    backfilling = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkSchemaState.State.BACKFILLING)
    if team_ids is not None:
        backfilling = backfilling.filter(team_id__in=team_ids)
    rows = list(backfilling)
    if not rows:
        return

    with psycopg.connect(settings.WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
        for state in rows:
            if not state.backfill_run_uuid:
                continue
            try:
                applied = conn.execute(
                    "SELECT count(*) FROM sourcebatchduckgresapply WHERE run_uuid = %s",
                    [state.backfill_run_uuid],
                ).fetchone()
                failed = conn.execute(
                    f"""
                    SELECT dgs.error_response->>'error'
                    FROM v_latest_source_batch_duckgres_status dgs
                    JOIN {BATCH_TABLE} b ON b.id = dgs.batch_id
                    WHERE b.run_uuid = %s AND dgs.job_state = 'failed'
                    LIMIT 1
                    """,
                    [state.backfill_run_uuid],
                ).fetchone()
            except Exception as e:
                logger.exception("duckgres_backfill_reconcile_failed", schema_id=str(state.schema_id))
                capture_exception(e)
                continue

            update_fields = ["updated_at"]
            if applied and applied[0] != state.chunks_applied:
                state.chunks_applied = applied[0]
                update_fields.append("chunks_applied")
            if failed is not None:
                reason = failed[0] or ""
                if "superseded" in reason:
                    state.state = DuckgresSinkSchemaState.State.PRIMED
                    update_fields.append("state")
                    logger.info(
                        "duckgres_backfill_superseded_by_live_refresh",
                        schema_id=str(state.schema_id),
                        run_uuid=state.backfill_run_uuid,
                    )
                elif state.last_error != reason:
                    state.last_error = reason[:2000]
                    update_fields.append("last_error")
            if len(update_fields) > 1:
                state.save(update_fields=update_fields)


def mark_primed(schema_id: str, *, chunks_applied: int | None = None) -> None:
    """Called by the processor after the swap commits."""
    updates: dict[str, Any] = {"state": DuckgresSinkSchemaState.State.PRIMED}
    if chunks_applied is not None:
        updates["chunks_applied"] = chunks_applied
    DuckgresSinkSchemaState.objects.filter(schema_id=schema_id).update(**updates)


def replan_backfill(schema_id: str) -> None:
    """Operator entrypoint: retire the old backfill run and re-enter planning."""
    state = DuckgresSinkSchemaState.objects.get(schema_id=schema_id)
    old_run = state.backfill_run_uuid
    if old_run:
        with psycopg.connect(settings.WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
            conn.execute(
                f"""
                INSERT INTO sourcebatchduckgresstatus (batch_id, job_state, attempt, error_response)
                SELECT b.id, 'failed', 0,
                       jsonb_build_object('error', 'superseded by backfill replan')
                FROM {BATCH_TABLE} b
                LEFT JOIN sourcebatchduckgresapply a
                    ON a.team_id = b.team_id AND a.schema_id = b.schema_id
                    AND a.run_uuid = b.run_uuid AND a.batch_index = b.batch_index
                WHERE b.run_uuid = %s
                    AND b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                    AND a.id IS NULL
                """,
                [old_run],
            )
    state.state = DuckgresSinkSchemaState.State.PENDING_BACKFILL
    state.snapshot_version = None
    state.backfill_run_uuid = None
    state.chunk_count = None
    state.chunks_applied = 0
    state.last_error = None
    state.save()


# ---------------------------------------------------------------------------
# Snapshot resolution & chunking
# ---------------------------------------------------------------------------


def _delta_table_uri(schema: ExternalDataSchema) -> str:
    return f"{settings.BUCKET_URL}/{schema.folder_path()}/{schema.normalized_name}"


def _resolve_snapshot_chunks(schema: ExternalDataSchema) -> tuple[int, list[BackfillChunk]]:
    from deltalake import DeltaTable

    from posthog.ducklake.storage import get_deltalake_storage_options

    uri = _delta_table_uri(schema)
    dt = DeltaTable(uri, storage_options=get_deltalake_storage_options())
    version = dt.version()

    if _has_deletion_vectors(dt):
        return version, _stage_snapshot(dt, schema, version)

    adds = dt.get_add_actions(flatten=True)
    paths = adds.column("path").to_pylist()
    sizes = adds.column("size_bytes").to_pylist()
    counts: list[int]
    try:
        counts = [int(c) if c is not None else 0 for c in adds.column("num_records").to_pylist()]
    except KeyError:
        counts = [0] * len(paths)

    files = [
        (f"{uri.rstrip('/')}/{p}" if not p.startswith(("s3://", "s3a://")) else p, s or 0, c or 0)
        for p, s, c in zip(paths, sizes, counts)
    ]
    return version, _group_files_into_chunks(files)


def _has_deletion_vectors(dt: Any) -> bool:
    """Conservative: a snapshot on a DV-enabled table stages even if no DV is
    currently active — re-deriving per-file DV state is not worth the risk of
    serving deleted rows."""
    try:
        protocol = dt.protocol()
        features = list(protocol.reader_features or [])
        return "deletionVectors" in features
    except Exception:
        return True  # unknown protocol shape: stage, never lie


def _group_files_into_chunks(files: list[tuple[str, int, int]]) -> list[BackfillChunk]:
    chunks: list[BackfillChunk] = []
    cur_paths: list[str] = []
    cur_bytes = 0
    cur_rows = 0
    for path, size, rows in files:
        if cur_paths and cur_bytes + size > CHUNK_TARGET_BYTES:
            chunks.append(BackfillChunk(len(chunks), cur_paths, cur_bytes, cur_rows))
            cur_paths, cur_bytes, cur_rows = [], 0, 0
        cur_paths.append(path)
        cur_bytes += size
        cur_rows += rows
    if cur_paths:
        chunks.append(BackfillChunk(len(chunks), cur_paths, cur_bytes, cur_rows))
    return chunks


def _stage_snapshot(dt: Any, schema: ExternalDataSchema, version: int) -> list[BackfillChunk]:
    """Stream the resolved snapshot to staging parquet chunks (bounded memory)."""
    import pyarrow.parquet as pq

    from products.data_warehouse.backend.s3 import get_s3_client

    s3 = get_s3_client()
    bucket = settings.BUCKET_URL.replace("s3://", "").rstrip("/")
    base = f"{bucket}/{STAGING_PREFIX}/{schema.id}/v{version}"

    chunks: list[BackfillChunk] = []
    reader = dt.to_pyarrow_dataset().scanner(batch_size=64_000).to_reader()
    writer: pq.ParquetWriter | None = None
    out: Any = None
    cur_bytes = 0
    cur_rows = 0

    def _rotate() -> None:
        nonlocal writer, out, cur_bytes, cur_rows
        if writer is not None:
            writer.close()
            if out is not None:
                out.close()
            chunks.append(
                BackfillChunk(len(chunks), [f"s3://{base}/chunk_{len(chunks):05d}.parquet"], cur_bytes, cur_rows)
            )
        writer, out, cur_bytes, cur_rows = None, None, 0, 0

    try:
        for batch in reader:
            if writer is None:
                out = s3.open(f"{base}/chunk_{len(chunks):05d}.parquet", "wb")
                writer = pq.ParquetWriter(out, batch.schema)
            writer.write_batch(batch)
            cur_bytes += batch.nbytes
            cur_rows += batch.num_rows
            if cur_bytes >= CHUNK_TARGET_BYTES:
                _rotate()
        _rotate()
    except Exception:
        if writer is not None:
            writer.close()
        if out is not None:
            out.close()
        raise

    logger.info(
        "duckgres_backfill_staged",
        schema_id=str(schema.id),
        version=version,
        chunk_count=len(chunks),
    )
    return chunks


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


def _enqueue_chunks(schema: ExternalDataSchema, run_uuid: str, chunks: list[BackfillChunk]) -> int:
    """Insert the synthetic run, idempotently (re-plans insert missing rows only).

    Every row is pre-marked delta-succeeded so the Delta consumer never claims
    it while the duckgres fetch sees it immediately.
    """
    inserted = 0
    with psycopg.connect(settings.WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
        existing = {
            row[0]
            for row in conn.execute(
                f"SELECT batch_index FROM {BATCH_TABLE} WHERE run_uuid = %s",
                [run_uuid],
            ).fetchall()
        }
        for chunk in chunks:
            if chunk.index in existing:
                continue
            batch_id = str(uuid.uuid4())
            conn.execute(
                f"""
                INSERT INTO {BATCH_TABLE} (
                    id, team_id, schema_id, source_id, job_id, run_uuid,
                    batch_index, s3_path, row_count, byte_size, is_final_batch,
                    total_batches, total_rows, sync_type, cumulative_row_count,
                    resource_name, is_resume, is_first_ever_sync, metadata
                ) VALUES (
                    %(id)s, %(team_id)s, %(schema_id)s, %(source_id)s, %(job_id)s, %(run_uuid)s,
                    %(batch_index)s, %(s3_path)s, %(row_count)s, %(byte_size)s, false,
                    %(total_batches)s, NULL, 'full_refresh', 0,
                    %(resource_name)s, true, false, %(metadata)s
                )
                """,
                {
                    "id": batch_id,
                    "team_id": schema.team_id,
                    "schema_id": str(schema.id),
                    "source_id": str(schema.source_id),
                    "job_id": BACKFILL_JOB_ID,
                    "run_uuid": run_uuid,
                    "batch_index": chunk.index,
                    "s3_path": chunk.paths[0],
                    "row_count": chunk.row_count,
                    "byte_size": chunk.byte_size,
                    "total_batches": len(chunks),
                    "resource_name": schema.name,
                    "metadata": psycopg.types.json.Jsonb(
                        {
                            "duckgres_backfill": True,
                            "chunk_paths": chunk.paths,
                            "chunk_count": len(chunks),
                        }
                    ),
                },
            )
            conn.execute(
                f"INSERT INTO {DELTA_STATUS_TABLE} (batch_id, job_state, attempt) VALUES (%s, 'succeeded', 1)",
                [batch_id],
            )
            inserted += 1
    return inserted


def _emit_state_gauge() -> None:
    counts = dict(DuckgresSinkSchemaState.objects.values_list("state").annotate(n=Count("id")))
    for state_value, _label in DuckgresSinkSchemaState.State.choices:
        BACKFILL_SCHEMAS_GAUGE.labels(state=state_value).set(counts.get(state_value, 0))


__all__ = [
    "BACKFILL_JOB_ID",
    "BackfillChunk",
    "backfill_run_uuid",
    "blocked_schema_ids",
    "mark_primed",
    "replan_backfill",
    "run_backfill_planner",
]
