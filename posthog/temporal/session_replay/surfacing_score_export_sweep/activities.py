"""Temporal activities for the surfacing-score export sweep.

Two activities:
    * `list_export_partitions_activity` — checks the export is configured and
      plans the (day × hash bucket) fan-out. Cheap.
    * `export_scores_partition_activity` — runs once per partition; does
      fetch (CH SELECT) → pseudonymize → Parquet encode → S3 put end to end.

Privacy contract:
    * Only teams whose organization opted into AI training are exported —
      the same gate the Node ML mirror applies before mirroring replay data,
      so scores never land in the ML account for sessions that were never
      mirrored.
    * Ids are pseudonymized with the ML mirror's exact HMAC scheme and key,
      so the exported `session_id`/`team_id` join onto the mirror's
      `block-metadata` dataset and nothing else.

Idempotency:
    * Object keys are deterministic per (day, chunk_id, of_chunks), so a
      retry or the daily re-export window simply overwrites the object.
    * A partition with no rows still writes an (empty) Parquet object —
      sessions deleted since the last run within the re-export window are
      thereby dropped from the dataset rather than left stale.
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


# --------------------------------------------------------------------------- #
# list_export_partitions_activity                                              #
# --------------------------------------------------------------------------- #


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
    """UTC days to (re-)export on a tick: complete days only, within the re-export window, never at or before the floor."""
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


# --------------------------------------------------------------------------- #
# export_scores_partition_activity                                             #
# --------------------------------------------------------------------------- #

_PARQUET_SCHEMA = pa.schema(
    [
        pa.field("session_id", pa.string(), nullable=False),
        pa.field("team_id", pa.string(), nullable=False),
        pa.field("started_at", pa.timestamp("ms", tz="UTC"), nullable=False),
        pa.field("surfacing_score", pa.float32(), nullable=False),
    ]
)


def _opted_in_team_ids() -> list[int]:
    return list(Team.objects.filter(organization__is_ai_training_opted_in=True).values_list("id", flat=True))


def _fetch_scored_sessions(spec: ExportPartitionSpec, team_ids: list[int]) -> list[tuple[int, str, datetime, float]]:
    return cast(
        list[tuple[int, str, datetime, float]],
        sync_execute(
            export_sql.fetch_scored_sessions_sql(),
            {
                "of_chunks": spec.of_chunks,
                "chunk_id": spec.chunk_id,
                "team_ids": team_ids,
                "day_start": f"{spec.day} 00:00:00",
            },
            settings={
                "max_execution_time": CH_EXPORT_QUERY_TIMEOUT_S,
                "max_memory_usage": CH_EXPORT_QUERY_MAX_MEMORY_BYTES,
            },
        ),
    )


def _rows_to_parquet(rows: list[tuple[int, str, datetime, float]], secret: bytes) -> bytes:
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
    # Cluster a team's sessions together for compression, like the ML mirror's store.
    records.sort(key=lambda r: (r["team_id"], r["session_id"]))
    table = pa.Table.from_pylist(records, schema=_PARQUET_SCHEMA)
    sink = io.BytesIO()
    pq.write_table(table, sink, compression="snappy")
    return sink.getvalue()


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
    """Export one (day, hash bucket) slice of scored sessions, end to end."""
    try:
        secret = await sync_to_async(resolve_pseudonym_key, thread_sensitive=False)()
    except (PseudonymKeyNotConfiguredError, PseudonymKeyFingerprintMismatchError) as e:
        raise ApplicationError(str(e), type=type(e).__name__, non_retryable=True) from e

    activity.heartbeat({"phase": "fetch", "day": spec.day, "chunk_id": spec.chunk_id})
    team_ids = await sync_to_async(_opted_in_team_ids, thread_sensitive=False)()
    rows: list[tuple[int, str, datetime, float]] = []
    if team_ids:
        rows = await sync_to_async(_fetch_scored_sessions, thread_sensitive=False)(spec, team_ids)

    activity.heartbeat({"phase": "encode", "day": spec.day, "chunk_id": spec.chunk_id, "rows": len(rows)})
    body = await sync_to_async(_rows_to_parquet, thread_sensitive=False)(rows, secret)

    activity.heartbeat({"phase": "upload", "day": spec.day, "chunk_id": spec.chunk_id})
    key = score_export_object_key(spec.day, spec.chunk_id, spec.of_chunks)
    await sync_to_async(_upload, thread_sensitive=False)(key, body)

    activity.logger.info(
        "surfacing_score_export_sweep.partition_done",
        day=spec.day,
        chunk_id=spec.chunk_id,
        rows=len(rows),
        bytes=len(body),
        key=key,
    )
    return ExportPartitionResult(day=spec.day, chunk_id=spec.chunk_id, rows=len(rows), bytes_written=len(body), key=key)
