"""Activities: plan the (day × hash bucket) fan-out, then per partition fetch → consent gate → Parquet → S3 put.

Rows carry the real team and session ids, the same ids the v2 ML mirror keys
its encrypted `block-metadata/v2` catalog by, so the two join directly. With
real ids there is no "opaque rows join to nothing" argument, so the export
applies the mirror's own consent gate: only sessions of organizations with
`is_ai_training_opted_in` set (NULL reads as opted out, as everywhere else)
are written, and only sessions the mirror itself stored under raw ids, which
it decides from the session id's UUIDv7 timestamp. Object keys are
deterministic, so retries and the re-export window overwrite; an empty
partition still writes an empty object so deleted sessions drop out rather
than going stale.
"""

from __future__ import annotations

import io
import time
import threading
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from asgiref.sync import sync_to_async
from boto3 import client as boto3_client
from botocore.client import Config
from temporalio import activity

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.temporal.session_replay.surfacing_score_export_sweep import sql as export_sql
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    BACKFILL_UNTIL,
    CH_EXPORT_QUERY_MAX_MEMORY_BYTES,
    CH_EXPORT_QUERY_TIMEOUT_S,
    DEFAULT_OF_CHUNKS,
    EXPORT_FLOOR_DAY,
    EXPORT_PAGE_MAX_ROWS,
    REEXPORT_WINDOW_DAYS,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.s3 import (
    score_export_destination,
    score_export_object_key,
    upload_parquet,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.session_identifier_format import (
    uses_raw_session_identifiers,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.types import (
    ExportPartitionResult,
    ExportPartitionSpec,
    ExportScoresSweepInputs,
    ListExportPartitionsResult,
)

logger = structlog.get_logger(__name__)


def _disabled_reason() -> str | None:
    if score_export_destination() is None:
        return "score export S3 destination not configured"
    return None


def export_days(today: date) -> list[str]:
    """Complete UTC days within the re-export window and temporary cutoff-day backfill."""
    window_start = EXPORT_FLOOR_DAY if today < BACKFILL_UNTIL else today - timedelta(days=REEXPORT_WINDOW_DAYS)
    first_day = max(EXPORT_FLOOR_DAY, window_start)
    days = []
    day = first_day
    while day < today:
        days.append(day.isoformat())
        day += timedelta(days=1)
    return days


@activity.defn
async def list_export_partitions_activity(_inputs: ExportScoresSweepInputs) -> ListExportPartitionsResult:
    reason = _disabled_reason()
    if reason is not None:
        logger.warning("surfacing_score_export_sweep.disabled", reason=reason)
        return ListExportPartitionsResult(disabled_reason=reason)

    days = export_days(datetime.now(UTC).date())
    partitions = [
        ExportPartitionSpec(day=d, chunk_id=chunk_id, of_chunks=DEFAULT_OF_CHUNKS)
        for d in days
        for chunk_id in range(DEFAULT_OF_CHUNKS)
    ]
    logger.info("surfacing_score_export_sweep.partitions_planned", days=len(days), partitions=len(partitions))
    return ListExportPartitionsResult(partitions=partitions)


_PARQUET_FIELDS: list[pa.Field[Any]] = [
    pa.field("session_id", pa.string(), nullable=False),
    pa.field("team_id", pa.string(), nullable=False),
    pa.field("started_at", pa.timestamp("ms", tz="UTC"), nullable=False),
    pa.field("surfacing_score", pa.float32(), nullable=False),
]
_PARQUET_SCHEMA = pa.schema(_PARQUET_FIELDS)


# (team_id, session_id, started_at, score)
_ScoredRow = tuple[int, str, datetime, float]


# Match the mirror's consent refresh interval.
OPTED_IN_TEAMS_TTL_S = 300

_opted_in_teams_lock = threading.Lock()
_opted_in_teams_cache: tuple[float, frozenset[int]] | None = None


def _opted_in_team_ids() -> frozenset[int]:
    """Return the mirror's consent gate, cached per worker across partition activities."""
    global _opted_in_teams_cache
    with _opted_in_teams_lock:
        cached = _opted_in_teams_cache
        if cached is not None and time.monotonic() - cached[0] < OPTED_IN_TEAMS_TTL_S:
            return cached[1]
        team_ids = frozenset(
            Team.objects.filter(organization__is_ai_training_opted_in=True).values_list("id", flat=True)
        )
        _opted_in_teams_cache = (time.monotonic(), team_ids)
        return team_ids


def _as_utc(started_at: datetime) -> datetime:
    return started_at.replace(tzinfo=UTC) if started_at.tzinfo is None else started_at


def exportable_rows(rows: list[_ScoredRow], opted_in_team_ids: frozenset[int]) -> tuple[list[_ScoredRow], int]:
    """Rows the export may carry, plus how many were dropped for missing consent or an id the mirror pseudonymized."""
    kept = [row for row in rows if row[0] in opted_in_team_ids and uses_raw_session_identifiers(row[1])]
    return kept, len(rows) - len(kept)


# Keyset cursor over the (session_id, team_id) page ordering; ("", 0) sorts before every real row.
_Cursor = tuple[str, int]
_FIRST_PAGE: _Cursor = ("", 0)


def _fetch_page(spec: ExportPartitionSpec, cursor: _Cursor) -> list[_ScoredRow]:
    return cast(
        list[_ScoredRow],
        sync_execute(
            export_sql.fetch_scored_sessions_page_sql(),
            {
                "of_chunks": spec.of_chunks,
                "chunk_id": spec.chunk_id,
                "day_start": f"{spec.day} 00:00:00",
                "cursor_session_id": cursor[0],
                "cursor_team_id": cursor[1],
                "page_size": EXPORT_PAGE_MAX_ROWS,
            },
            settings={
                "max_execution_time": CH_EXPORT_QUERY_TIMEOUT_S,
                "max_memory_usage": CH_EXPORT_QUERY_MAX_MEMORY_BYTES,
            },
        ),
    )


def _page_table(rows: list[_ScoredRow]) -> pa.Table:
    # team_id stays a string so the Glue column type matches the pseudonymized dataset.
    records: list[dict[str, Any]] = [
        {
            "session_id": session_id,
            "team_id": str(team_id),
            "started_at": _as_utc(started_at),
            "surfacing_score": float(score),
        }
        for team_id, session_id, started_at, score in rows
    ]
    return pa.Table.from_pylist(records, schema=_PARQUET_SCHEMA)


def _upload(key: str, body: bytes) -> None:
    dest = score_export_destination()
    if dest is None:
        raise RuntimeError("score export S3 destination not configured")
    s3 = boto3_client(
        "s3",
        endpoint_url=dest.endpoint,
        aws_access_key_id=dest.access_key_id,
        aws_secret_access_key=dest.secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name=dest.region,
    )
    upload_parquet(s3, bucket=dest.bucket, key=key, body=body)


@activity.defn
async def export_scores_partition_activity(spec: ExportPartitionSpec) -> ExportPartitionResult:
    opted_in_team_ids = await sync_to_async(_opted_in_team_ids, thread_sensitive=False)()

    activity.heartbeat({"phase": "fetch", "day": spec.day, "chunk_id": spec.chunk_id})

    sink = io.BytesIO()
    writer = pq.ParquetWriter(sink, _PARQUET_SCHEMA, compression="snappy")
    cursor = _FIRST_PAGE
    rows_total = 0
    rows_dropped = 0
    try:
        while True:
            rows = await sync_to_async(_fetch_page, thread_sensitive=False)(spec, cursor)
            if rows:
                kept, dropped = exportable_rows(rows, opted_in_team_ids)
                rows_dropped += dropped
                table = await sync_to_async(_page_table, thread_sensitive=False)(kept)
                await sync_to_async(writer.write_table, thread_sensitive=False)(table)
                rows_total += len(kept)
                # Keyed on the fetched page, not the kept rows, or a dropped tail would stall the scan.
                cursor = (rows[-1][1], rows[-1][0])
            if len(rows) < EXPORT_PAGE_MAX_ROWS:
                break
            activity.heartbeat({"phase": "fetch", "day": spec.day, "chunk_id": spec.chunk_id, "rows": rows_total})
    finally:
        writer.close()
    body = sink.getvalue()

    activity.heartbeat({"phase": "upload", "day": spec.day, "chunk_id": spec.chunk_id, "rows": rows_total})
    key = score_export_object_key(spec.day, spec.chunk_id, spec.of_chunks)
    await sync_to_async(_upload, thread_sensitive=False)(key, body)

    logger.info(
        "surfacing_score_export_sweep.partition_done",
        day=spec.day,
        chunk_id=spec.chunk_id,
        rows=rows_total,
        rows_dropped=rows_dropped,
        bytes=len(body),
        key=key,
    )
    return ExportPartitionResult(
        day=spec.day, chunk_id=spec.chunk_id, rows=rows_total, bytes_written=len(body), key=key
    )
