"""Backfill primer for the Duckgres batch sink.

Pre-existing incremental/append schemas have history in Delta that the sink's
per-batch stream will never replay. This module backfills that history with
bounded memory and resume-from-checkpoint:

1. Pin a Delta snapshot and derive chunk groups (~1 GiB of the table's own
   live parquet files per chunk — metadata only, zero data movement).
   Tables with the deletionVectors reader feature are NOT backfillable with
   the installed deltalake (it cannot stream DV tables); they park in
   NEEDS_RESYNC with a clear error and heal via a full-refresh resync.
2. Retire the schema's pre-snapshot queue runs (their data is inside the
   pinned snapshot by construction) so the cross-run gate opens for the
   backfill run instead of deadlocking behind blocked live batches.
3. Enqueue the chunks as a synthetic "backfill run" in the regular queue,
   pre-marked delta-succeeded (invisible to the Delta consumer, immediately
   eligible for the duckgres fetch). Batch row + status row commit together.
4. The normal sink consumer applies chunks into ``<table>__bf_<id>``; the
   last chunk atomically swaps it over the live table (processor.py).

Concurrency: the planner runs in EVERY consumer pod's maintenance tick. All
state transitions are compare-and-swap UPDATEs on DuckgresSinkSchemaState, so
exactly one pod wins each claim; everything downstream of a claim is
idempotent (chunk enqueue keyed by the state row's run_uuid, apply markers on
the duckgres side).

The planner is sync (Django ORM + psycopg + deltalake); the consumer invokes
it from its maintenance tick via sync_to_async.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from django.conf import settings
from django.db import close_old_connections
from django.db.models import Count
from django.utils import timezone

import psycopg
import structlog
from prometheus_client import Gauge

from posthog.exceptions_capture import capture_exception
from posthog.models import DuckgresSinkSchemaState
from posthog.temporal.data_imports.pipelines.pipeline_v3.duckgres.jobs_db import RETIRE_KIND_SUPERSEDED_BY_REPLACE
from posthog.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    PARTITION_PRUNING_INTERVAL,
    STATUS_TABLE as DELTA_STATUS_TABLE,
)

from products.warehouse_sources.backend.models import ExternalDataSchema

logger = structlog.get_logger(__name__)

BACKFILL_JOB_ID = "duckgres-backfill"
CHUNK_TARGET_BYTES = 1024**3  # ~1 GiB of parquet per chunk statement
MAX_FILES_PER_CHUNK = 512  # bound the read_parquet([...]) literal list
MAX_CONCURRENT_BACKFILLS_PER_ORG = 1  # best-effort across pods (see _plan_pending)

# Reasons written into duckgres status rows. _reconcile_backfilling matches on
# these prefixes — keep them distinct: only a LIVE replace-run supersession may
# flip a schema to PRIMED.
REASON_SUPERSEDED_BY_REPLACE = "superseded by newer replace run"  # written by supersede_replaced_runs
REASON_COVERED_BY_SNAPSHOT = "covered by duckgres backfill snapshot"
REASON_RETIRED_BY_REPLAN = "retired by backfill replan"

# Structured kinds for this module's own terminal-retire writers.
RETIRE_KIND_COVERED_BY_SNAPSHOT = "covered_by_backfill_snapshot"
RETIRE_KIND_RETIRED_BY_REPLAN = "retired_by_backfill_replan"

BACKFILL_SCHEMAS_GAUGE = Gauge(
    "duckgres_backfill_schemas",
    "Duckgres sink schemas per backfill lifecycle state",
    labelnames=["state"],
    multiprocess_mode="livemax",
)


class BackfillUnsupportedError(Exception):
    """The Delta table cannot be backfilled by this planner (parks NEEDS_RESYNC)."""


@dataclass(frozen=True)
class BackfillChunk:
    index: int
    paths: list[str]
    byte_size: int
    row_count: int


def backfill_run_uuid(schema_id: str, snapshot_version: int) -> str:
    """Unique per planning attempt: the generation nonce guarantees a replan at
    an unadvanced Delta version still gets a fresh, claimable run."""
    return f"{BACKFILL_JOB_ID}-{schema_id}-v{snapshot_version}-g{uuid.uuid4().hex[:8]}"


def run_backfill_planner(team_ids: list[int] | None) -> None:
    """One planner pass: bootstrap state rows, reconcile in-flight, plan pending.

    Per-schema failures are isolated; called from the consumer's maintenance
    tick (sync_to_async, thread_sensitive=False).
    """
    close_old_connections()
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
    planner pass where a pre-existing schema's live batches sneak in.
    """
    close_old_connections()
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

    Straight to PRIMED when no priming is needed:
    - full_refresh: every run's batch 0 replaces the table completely.
    - no Delta table yet: the first sync creates everything.
    - cdc: the sink rejects CDC batches outright; do not block the queue on it.
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

    # Oldest-touched first so a failing schema cannot starve the rest of the slice.
    for state in pending.select_related("team").order_by("updated_at")[:50]:
        org_id = state.team.organization_id
        if _org_busy(org_id):
            continue

        # CAS claim: exactly one pod transitions PENDING -> BACKFILLING.
        claimed = DuckgresSinkSchemaState.objects.filter(
            id=state.id, state=DuckgresSinkSchemaState.State.PENDING_BACKFILL
        ).update(state=DuckgresSinkSchemaState.State.BACKFILLING, updated_at=timezone.now())
        if not claimed:
            continue

        # Re-check the org cap after winning the claim; the pre-check raced
        # against other pods. (Still best-effort across orgs — a transient
        # second concurrent backfill per org is wasteful, not incorrect.)
        if (
            DuckgresSinkSchemaState.objects.filter(
                state=DuckgresSinkSchemaState.State.BACKFILLING,
                team__organization_id=org_id,
            )
            .exclude(id=state.id)
            .exists()
        ):
            _revert_to_pending(state.id)
            continue

        try:
            _plan_one(state)
        except BackfillUnsupportedError as e:
            DuckgresSinkSchemaState.objects.filter(id=state.id).update(
                state=DuckgresSinkSchemaState.State.NEEDS_RESYNC,
                last_error=str(e)[:2000],
                updated_at=timezone.now(),
            )
            logger.warning("duckgres_backfill_unsupported", schema_id=str(state.schema_id), error=str(e))
        except Exception as e:
            logger.exception("duckgres_backfill_plan_failed", schema_id=str(state.schema_id))
            capture_exception(e)
            _revert_to_pending(state.id, error=str(e)[:2000])


def _org_busy(org_id: Any) -> bool:
    return (
        DuckgresSinkSchemaState.objects.filter(
            state=DuckgresSinkSchemaState.State.BACKFILLING,
            team__organization_id=org_id,
        ).count()
        >= MAX_CONCURRENT_BACKFILLS_PER_ORG
    )


def _revert_to_pending(state_id: Any, error: str | None = None) -> None:
    updates: dict[str, Any] = {
        "state": DuckgresSinkSchemaState.State.PENDING_BACKFILL,
        "updated_at": timezone.now(),
    }
    if error is not None:
        updates["last_error"] = error
    DuckgresSinkSchemaState.objects.filter(
        id=state_id, state=DuckgresSinkSchemaState.State.BACKFILLING, backfill_run_uuid__isnull=True
    ).update(**updates)


def _plan_one(state: DuckgresSinkSchemaState) -> None:
    """Runs only on the pod that won the CAS claim."""
    schema = ExternalDataSchema.objects.select_related("source", "team").get(id=state.schema_id)

    snapshot_version, chunks = _resolve_snapshot_chunks(schema)
    if not chunks:
        # Empty Delta table: nothing to prime.
        DuckgresSinkSchemaState.objects.filter(id=state.id).update(
            state=DuckgresSinkSchemaState.State.PRIMED, updated_at=timezone.now()
        )
        return

    run_uuid = backfill_run_uuid(str(state.schema_id), snapshot_version)

    with psycopg.connect(settings.WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
        # Retire the schema's pre-snapshot live runs FIRST: their rows are
        # delta-succeeded but blocked (schema not PRIMED), so they would gate
        # the backfill run via the cross-run head-of-line check forever. Their
        # data is inside the pinned snapshot by construction, so failing them
        # is semantically the same as the supersede sweep.
        retired = _retire_schema_runs(
            conn,
            team_id=schema.team_id,
            schema_id=str(state.schema_id),
            reason=f"{REASON_COVERED_BY_SNAPSHOT} v{snapshot_version}",
        )
        inserted = _enqueue_chunks(conn, schema, run_uuid, chunks)

    DuckgresSinkSchemaState.objects.filter(id=state.id).update(
        state=DuckgresSinkSchemaState.State.BACKFILLING,
        snapshot_version=snapshot_version,
        backfill_run_uuid=run_uuid,
        chunk_count=len(chunks),
        chunks_applied=0,
        last_error=None,
        updated_at=timezone.now(),
    )
    logger.info(
        "duckgres_backfill_planned",
        schema_id=str(state.schema_id),
        team_id=schema.team_id,
        run_uuid=run_uuid,
        snapshot_version=snapshot_version,
        chunk_count=len(chunks),
        inserted=inserted,
        retired_live_batches=retired,
        total_bytes=sum(c.byte_size for c in chunks),
    )


def _reconcile_backfilling(team_ids: list[int] | None) -> None:
    """Heal and progress in-flight backfills. Authoritative for PRIMED:

    - chunks_applied == chunk_count ⇒ the swap committed (the last chunk's
      apply marker shares the swap's transaction) ⇒ PRIMED, even if the
      post-swap mark_primed call was lost to a crash or app-DB blip.
    - A run superseded by a LIVE replace run ⇒ PRIMED (the replace produces
      the complete table; it is unblocked the moment PRIMED lands).
    - Queue rows dropped by 7-day retention before completion are re-enqueued
      at the pinned snapshot version (idempotent by (run_uuid, batch_index)).
    - Any other failure surfaces on last_error and the schema stays
      BACKFILLING (alerting surface; operator replans).
    """
    backfilling = DuckgresSinkSchemaState.objects.filter(state=DuckgresSinkSchemaState.State.BACKFILLING)
    if team_ids is not None:
        backfilling = backfilling.filter(team_id__in=team_ids)
    rows = [s for s in backfilling if s.backfill_run_uuid]
    if not rows:
        return

    with psycopg.connect(settings.WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
        for state in rows:
            try:
                _reconcile_one(conn, state)
            except Exception as e:
                logger.exception("duckgres_backfill_reconcile_failed", schema_id=str(state.schema_id))
                capture_exception(e)


def _reconcile_one(conn: psycopg.Connection[Any], state: DuckgresSinkSchemaState) -> None:
    run_uuid = state.backfill_run_uuid
    applied_row = conn.execute(
        "SELECT count(*) FROM sourcebatchduckgresapply WHERE run_uuid = %s", [run_uuid]
    ).fetchone()
    applied = int(applied_row[0]) if applied_row else 0

    if state.chunk_count and applied >= state.chunk_count:
        # Full application proves the swap committed. CAS so a stale pass can
        # never resurrect a state another pod already advanced.
        DuckgresSinkSchemaState.objects.filter(id=state.id, state=DuckgresSinkSchemaState.State.BACKFILLING).update(
            state=DuckgresSinkSchemaState.State.PRIMED,
            chunks_applied=applied,
            updated_at=timezone.now(),
        )
        return

    failed = conn.execute(
        f"""
        SELECT dgs.error_response->>'error', dgs.error_response->>'kind'
        FROM v_latest_source_batch_duckgres_status dgs
        JOIN {BATCH_TABLE} b ON b.id = dgs.batch_id
        WHERE b.run_uuid = %s AND dgs.job_state = 'failed'
        LIMIT 1
        """,
        [run_uuid],
    ).fetchone()

    if failed is not None:
        reason = failed[0] or ""
        kind = failed[1]
        # Structured dispatch; the prefix fallback covers status rows written
        # before 'kind' existed.
        superseded_by_replace = kind == RETIRE_KIND_SUPERSEDED_BY_REPLACE or (
            kind is None and reason.startswith(REASON_SUPERSEDED_BY_REPLACE)
        )
        if superseded_by_replace:
            DuckgresSinkSchemaState.objects.filter(id=state.id, state=DuckgresSinkSchemaState.State.BACKFILLING).update(
                state=DuckgresSinkSchemaState.State.PRIMED, updated_at=timezone.now()
            )
            logger.info(
                "duckgres_backfill_superseded_by_live_refresh",
                schema_id=str(state.schema_id),
                run_uuid=run_uuid,
            )
        elif state.last_error != reason:
            DuckgresSinkSchemaState.objects.filter(id=state.id).update(
                last_error=reason[:2000], chunks_applied=applied, updated_at=timezone.now()
            )
        return

    # Healthy in-flight run: track progress and re-enqueue rows lost to the
    # queue's 7-day partition retention (apply markers persist 30d, so resume
    # is exact).
    present_row = conn.execute(f"SELECT count(*) FROM {BATCH_TABLE} WHERE run_uuid = %s", [run_uuid]).fetchone()
    present = int(present_row[0]) if present_row else 0
    if state.chunk_count and present < state.chunk_count and state.snapshot_version is not None:
        schema = ExternalDataSchema.objects.select_related("source").get(id=state.schema_id)
        _, chunks = _resolve_snapshot_chunks(schema, version=state.snapshot_version)
        reinserted = _enqueue_chunks(conn, schema, str(run_uuid), chunks)
        if reinserted:
            logger.info(
                "duckgres_backfill_reenqueued_dropped_chunks",
                schema_id=str(state.schema_id),
                run_uuid=run_uuid,
                reinserted=reinserted,
            )

    if applied != state.chunks_applied:
        DuckgresSinkSchemaState.objects.filter(id=state.id).update(chunks_applied=applied, updated_at=timezone.now())


def mark_primed(schema_id: str, *, chunks_applied: int | None = None) -> None:
    """Fast path called by the processor right after the swap commits.

    CAS from BACKFILLING only — reconcile is the authoritative healer, and a
    late call must never clobber a state that has since moved on.
    """
    updates: dict[str, Any] = {
        "state": DuckgresSinkSchemaState.State.PRIMED,
        "updated_at": timezone.now(),
    }
    if chunks_applied is not None:
        updates["chunks_applied"] = chunks_applied
    DuckgresSinkSchemaState.objects.filter(schema_id=schema_id, state=DuckgresSinkSchemaState.State.BACKFILLING).update(
        **updates
    )


def replan_backfill(schema_id: str) -> None:
    """Operator entrypoint: retire the current backfill run and re-enter planning.

    The retire reason is deliberately NOT the live-supersede prefix, so the
    reconcile pass can never mistake a replan for a completed live refresh.
    The next plan gets a fresh generation nonce, so an unadvanced Delta
    version still yields a new, claimable run.
    """
    state = DuckgresSinkSchemaState.objects.get(schema_id=schema_id)
    old_run = state.backfill_run_uuid
    if old_run:
        with psycopg.connect(settings.WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
            conn.execute(
                f"""
                INSERT INTO sourcebatchduckgresstatus (batch_id, job_state, attempt, error_response)
                SELECT b.id, 'failed', 0, jsonb_build_object('error', %(reason)s, 'kind', %(kind)s)
                FROM {BATCH_TABLE} b
                LEFT JOIN sourcebatchduckgresapply a
                    ON a.team_id = b.team_id AND a.schema_id = b.schema_id
                    AND a.run_uuid = b.run_uuid AND a.batch_index = b.batch_index
                WHERE b.run_uuid = %(run_uuid)s
                    AND b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                    AND a.id IS NULL
                """,
                {"run_uuid": old_run, "reason": REASON_RETIRED_BY_REPLAN, "kind": RETIRE_KIND_RETIRED_BY_REPLAN},
            )
    DuckgresSinkSchemaState.objects.filter(id=state.id).update(
        state=DuckgresSinkSchemaState.State.PENDING_BACKFILL,
        snapshot_version=None,
        backfill_run_uuid=None,
        chunk_count=None,
        chunks_applied=0,
        last_error=None,
        updated_at=timezone.now(),
    )


# ---------------------------------------------------------------------------
# Snapshot resolution & chunking
# ---------------------------------------------------------------------------


def _delta_table_uri(schema: ExternalDataSchema) -> str:
    return f"{settings.BUCKET_URL}/{schema.folder_path()}/{schema.normalized_name}"


def _delta_storage_options() -> dict[str, str]:
    """Storage options for metadata-only Delta log reads from the consumer pod.

    Prod: empty — deltalake's object_store resolves the pod's ambient AWS
    credential chain (IRSA/env) itself. Local dev: MinIO endpoint + keys.
    (posthog.ducklake.storage.get_deltalake_storage_options is NOT usable
    here: it requires DuckLake RDS env that consumer pods do not carry.)
    """
    if settings.USE_LOCAL_SETUP:
        return {
            "AWS_ACCESS_KEY_ID": settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            "AWS_SECRET_ACCESS_KEY": settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            "AWS_ENDPOINT_URL": settings.OBJECT_STORAGE_ENDPOINT,
            "AWS_ALLOW_HTTP": "true",
            "AWS_REGION": "us-east-1",
        }
    return {}


def _resolve_snapshot_chunks(schema: ExternalDataSchema, version: int | None = None) -> tuple[int, list[BackfillChunk]]:
    from deltalake import DeltaTable

    uri = _delta_table_uri(schema)
    dt = DeltaTable(uri, version=version, storage_options=_delta_storage_options())
    resolved_version = dt.version()

    if _has_deletion_vectors(dt):
        # deltalake 1.4.0 cannot stream DV tables (to_pyarrow_dataset rejects
        # the reader feature), and reading the add files directly would serve
        # deleted rows. Park the schema; a full-refresh resync heals it.
        raise BackfillUnsupportedError(
            "Delta table has the deletionVectors reader feature; backfill requires a full resync"
        )

    adds = dt.get_add_actions(flatten=True)
    paths = adds.column("path").to_pylist()
    sizes = adds.column("size_bytes").to_pylist()
    counts: list[int]
    try:
        counts = [int(c) if c is not None else 0 for c in adds.column("num_records").to_pylist()]
    except KeyError:
        counts = [0] * len(paths)

    files = []
    for p, size, rows in zip(paths, sizes, counts):
        # Add-action paths are percent-encoded relative paths (or, rarely,
        # absolute URIs). Decode so read_parquet sees the real object key.
        decoded = unquote(p)
        full = decoded if decoded.startswith(("s3://", "s3a://")) else f"{uri.rstrip('/')}/{decoded}"
        files.append((full, size or 0, rows or 0))
    return resolved_version, _group_files_into_chunks(files)


def _has_deletion_vectors(dt: Any) -> bool:
    """Conservative: a DV-enabled table parks even if no DV is currently active —
    re-deriving per-file DV state is not worth the risk of serving deleted rows."""
    try:
        protocol = dt.protocol()
        features = list(protocol.reader_features or [])
        return "deletionVectors" in features
    except Exception:
        return True  # unknown protocol shape: park, never lie


def _group_files_into_chunks(files: list[tuple[str, int, int]]) -> list[BackfillChunk]:
    chunks: list[BackfillChunk] = []
    cur_paths: list[str] = []
    cur_bytes = 0
    cur_rows = 0
    for path, size, rows in files:
        if cur_paths and (cur_bytes + size > CHUNK_TARGET_BYTES or len(cur_paths) >= MAX_FILES_PER_CHUNK):
            chunks.append(BackfillChunk(len(chunks), cur_paths, cur_bytes, cur_rows))
            cur_paths, cur_bytes, cur_rows = [], 0, 0
        cur_paths.append(path)
        cur_bytes += size
        cur_rows += rows
    if cur_paths:
        chunks.append(BackfillChunk(len(chunks), cur_paths, cur_bytes, cur_rows))
    return chunks


# ---------------------------------------------------------------------------
# Queue writes
# ---------------------------------------------------------------------------


def _retire_schema_runs(
    conn: psycopg.Connection[Any],
    *,
    team_id: int,
    schema_id: str,
    reason: str,
) -> int:
    """Fail every unapplied, non-terminal batch of the schema's existing runs.

    Called at plan time, before the backfill rows exist: everything currently
    queued for the schema predates the pinned snapshot, so its data is in the
    snapshot. Skips 'executing' batches (a mid-flight attempt resolves itself;
    its siblings' failed rows already retire the run from the gates).
    """
    cursor = conn.execute(
        f"""
        INSERT INTO sourcebatchduckgresstatus (batch_id, job_state, attempt, error_response)
        SELECT b.id, 'failed', 0, jsonb_build_object('error', %(reason)s, 'kind', %(kind)s)
        FROM {BATCH_TABLE} b
        LEFT JOIN v_latest_source_batch_duckgres_status dgs ON b.id = dgs.batch_id
        LEFT JOIN sourcebatchduckgresapply a
            ON a.team_id = b.team_id AND a.schema_id = b.schema_id
            AND a.run_uuid = b.run_uuid AND a.batch_index = b.batch_index
        WHERE b.team_id = %(team_id)s
            AND b.schema_id = %(schema_id)s
            AND b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
            AND (b.is_final_batch = true OR a.id IS NULL)
            AND (dgs.batch_id IS NULL OR dgs.job_state = 'waiting_retry')
        """,
        {"team_id": team_id, "schema_id": schema_id, "reason": reason, "kind": RETIRE_KIND_COVERED_BY_SNAPSHOT},
    )
    return cursor.rowcount or 0


def _enqueue_chunks(
    conn: psycopg.Connection[Any],
    schema: ExternalDataSchema,
    run_uuid: str,
    chunks: list[BackfillChunk],
) -> int:
    """Insert the synthetic run, idempotently by (run_uuid, batch_index).

    Each batch row and its pre-succeeded Delta status row commit in ONE
    transaction: a synthetic row visible without 'succeeded' status would be
    claimed by the Delta consumer and loaded into the Delta table.
    """
    inserted = 0
    existing = {
        row[0]
        for row in conn.execute(f"SELECT batch_index FROM {BATCH_TABLE} WHERE run_uuid = %s", [run_uuid]).fetchall()
    }
    for chunk in chunks:
        if chunk.index in existing:
            continue
        batch_id = str(uuid.uuid4())
        with conn.transaction():
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
    "BackfillUnsupportedError",
    "backfill_run_uuid",
    "blocked_schema_ids",
    "mark_primed",
    "replan_backfill",
    "run_backfill_planner",
]
