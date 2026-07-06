"""Activities: plan the (day × hash bucket) fan-out, then per partition fetch → pseudonymize → Parquet → S3 put.

Only AI-training opted-in orgs are exported (the ML mirror's gate), with the
mirror's exact pseudonym scheme, so exported ids join onto `block-metadata`
and nothing else. Object keys are deterministic, so retries and the re-export
window overwrite; an empty partition still writes an empty object so deleted
sessions drop out rather than going stale.
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from django.conf import settings

import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from asgiref.sync import sync_to_async
from boto3 import client as boto3_client
from botocore.client import Config
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.temporal.session_replay.surfacing_score_export_sweep import sql as export_sql
from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    CH_EXPORT_QUERY_MAX_MEMORY_BYTES,
    CH_EXPORT_QUERY_TIMEOUT_S,
    DEFAULT_OF_CHUNKS,
    EXPORT_FLOOR_DAY,
    EXPORT_PAGE_MAX_ROWS,
    REEXPORT_WINDOW_DAYS,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.pseudonymize import (
    PSEUDONYM_SESSION,
    PSEUDONYM_TEAM,
    PseudonymKeyFingerprintMismatchError,
    PseudonymKeyNotConfiguredError,
    is_pseudonym_key_configured,
    pseudonymize,
    resolve_pseudonym_key,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.s3 import score_export_object_key, upload_parquet
from posthog.temporal.session_replay.surfacing_score_export_sweep.types import (
    ExportPartitionResult,
    ExportPartitionSpec,
    ExportScoresSweepInputs,
    ListExportPartitionsResult,
)

logger = structlog.get_logger(__name__)


def _disabled_reason() -> str | None:
    if not is_pseudonym_key_configured():
        return "pseudonym key not configured"
    if not all(
        [
            settings.SESSION_RECORDING_V2_S3_ENDPOINT,
            settings.SESSION_RECORDING_V2_S3_REGION,
            settings.SESSION_RECORDING_V2_S3_BUCKET,
        ]
    ):
        return "session recording v2 S3 destination not configured"
    return None


def export_days(today: date) -> list[str]:
    """Complete UTC days within the re-export window, never before the floor."""
    first_day = max(EXPORT_FLOOR_DAY, today - timedelta(days=REEXPORT_WINDOW_DAYS))
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


def _opted_in_team_ids() -> list[int]:
    return list(Team.objects.filter(organization__is_ai_training_opted_in=True).values_list("id", flat=True))


# (team_id, session_id, started_at, score)
_ScoredRow = tuple[int, str, datetime, float]

# Keyset cursor over the (session_id, team_id) page ordering; ("", 0) sorts before every real row.
_Cursor = tuple[str, int]
_FIRST_PAGE: _Cursor = ("", 0)


def _fetch_page(spec: ExportPartitionSpec, team_ids: list[int], cursor: _Cursor) -> list[_ScoredRow]:
    return cast(
        list[_ScoredRow],
        sync_execute(
            export_sql.fetch_scored_sessions_page_sql(),
            {
                "of_chunks": spec.of_chunks,
                "chunk_id": spec.chunk_id,
                "team_ids": team_ids,
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


def _page_table(rows: list[_ScoredRow], secret: bytes) -> pa.Table:
    records: list[dict[str, Any]] = []
    for team_id, session_id, started_at, score in rows:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        records.append(
            {
                "session_id": pseudonymize(secret, PSEUDONYM_SESSION, session_id),
                "team_id": pseudonymize(secret, PSEUDONYM_TEAM, str(team_id)),
                "started_at": started_at,
                "surfacing_score": float(score),
            }
        )
    return pa.Table.from_pylist(records, schema=_PARQUET_SCHEMA)


def _upload(key: str, body: bytes) -> None:
    s3 = boto3_client(
        "s3",
        endpoint_url=settings.SESSION_RECORDING_V2_S3_ENDPOINT,
        aws_access_key_id=settings.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name=settings.SESSION_RECORDING_V2_S3_REGION,
    )
    upload_parquet(s3, bucket=settings.SESSION_RECORDING_V2_S3_BUCKET, key=key, body=body)


@activity.defn
async def export_scores_partition_activity(spec: ExportPartitionSpec) -> ExportPartitionResult:
    try:
        secret = await sync_to_async(resolve_pseudonym_key, thread_sensitive=False)()
    except (PseudonymKeyNotConfiguredError, PseudonymKeyFingerprintMismatchError) as e:
        raise ApplicationError(str(e), type=type(e).__name__, non_retryable=True) from e

    activity.heartbeat({"phase": "fetch", "day": spec.day, "chunk_id": spec.chunk_id})
    team_ids = await sync_to_async(_opted_in_team_ids, thread_sensitive=False)()

    sink = io.BytesIO()
    writer = pq.ParquetWriter(sink, _PARQUET_SCHEMA, compression="snappy")
    cursor = _FIRST_PAGE
    rows_total = 0
    try:
        while team_ids:
            rows = await sync_to_async(_fetch_page, thread_sensitive=False)(spec, team_ids, cursor)
            if rows:
                table = await sync_to_async(_page_table, thread_sensitive=False)(rows, secret)
                await sync_to_async(writer.write_table, thread_sensitive=False)(table)
                rows_total += len(rows)
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

    activity.logger.info(
        "surfacing_score_export_sweep.partition_done",
        day=spec.day,
        chunk_id=spec.chunk_id,
        rows=rows_total,
        bytes=len(body),
        key=key,
    )
    return ExportPartitionResult(
        day=spec.day, chunk_id=spec.chunk_id, rows=rows_total, bytes_written=len(body), key=key
    )
