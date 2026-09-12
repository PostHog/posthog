"""Activities: plan the (day × hash bucket) fan-out, then per partition fetch → Parquet → S3 put.

Session start time selects raw identifiers or legacy HMAC pseudonyms.
Training datasets must join these scores to opted-in mirror sessions.
Object keys are deterministic, so retries and the re-export window overwrite;
an empty partition still writes an empty object so deleted sessions drop out
rather than going stale.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
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

from posthog.ai_training_privacy_reader import DynamoReader, KmsReader, TrainingDataKeyReader, TrainingKeyLocation
from posthog.clickhouse.client import sync_execute
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
    pseudonymize,
    resolve_pseudonym_key,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.s3 import (
    score_export_destination,
    score_export_object_key,
    score_export_prefix,
    upload_parquet,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.session_identifier_format import (
    RAW_SESSION_IDENTIFIERS_START_MS,
    uses_raw_session_identifiers,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.types import (
    EncryptedScoreManifest,
    EncryptedScorePage,
    EncryptedScorePageResult,
    EncryptedScorePlan,
    EncryptedScorePlanInput,
    ExportPartitionResult,
    ExportPartitionSpec,
    ExportScoresSweepInputs,
    ListExportPartitionsResult,
    ScoreCursor,
)

logger = structlog.get_logger(__name__)


def _disabled_reason() -> str | None:
    if score_export_destination() is None:
        return "score export S3 destination not configured"
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
        ExportPartitionSpec(
            day=d,
            chunk_id=chunk_id,
            of_chunks=DEFAULT_OF_CHUNKS,
            encrypted_enabled=bool(settings.AI_RESEARCH_REPLAY_PRIVACY_TABLE),
        )
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

# Keyset cursor over the (session_id, team_id) page ordering; ("", 0) sorts before every real row.
_Cursor = tuple[str, int]
_FIRST_PAGE: _Cursor = ("", 0)


def _fetch_page(spec: ExportPartitionSpec, cursor: _Cursor, page_size: int = EXPORT_PAGE_MAX_ROWS) -> list[_ScoredRow]:
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
                "page_size": page_size,
            },
            settings={
                "max_execution_time": CH_EXPORT_QUERY_TIMEOUT_S,
                "max_memory_usage": CH_EXPORT_QUERY_MAX_MEMORY_BYTES,
            },
        ),
    )


def _page_table(rows: list[_ScoredRow], secret: bytes | None = None) -> pa.Table:
    records: list[dict[str, Any]] = []
    for team_id, session_id, started_at, score in rows:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        records.append(
            {
                "session_id": pseudonymize(secret, PSEUDONYM_SESSION, session_id) if secret is not None else session_id,
                "team_id": pseudonymize(secret, PSEUDONYM_TEAM, str(team_id)) if secret is not None else str(team_id),
                "started_at": started_at,
                "surfacing_score": float(score),
            }
        )
    return pa.Table.from_pylist(records, schema=_PARQUET_SCHEMA)


_ENCRYPTED_SCORE_FIELDS: list[pa.Field[Any]] = [
    pa.field("session_id", pa.string(), nullable=False),
    pa.field("team_id", pa.string(), nullable=False),
    pa.field("consent_granted_at", pa.int64(), nullable=False),
    pa.field("payload", pa.binary(), nullable=False),
]
_ENCRYPTED_SCORE_SCHEMA = pa.schema(_ENCRYPTED_SCORE_FIELDS)


@lru_cache(maxsize=1)
def _score_key_reader() -> TrainingDataKeyReader:
    if not settings.AI_RESEARCH_REPLAY_PRIVACY_TABLE or not settings.AI_RESEARCH_REPLAY_KMS_KEY_ARN:
        raise RuntimeError("ML v2 score export requires privacy configuration")
    config = Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 3, "mode": "standard"})
    dynamo = boto3_client(
        "dynamodb",
        region_name=settings.AI_RESEARCH_REPLAY_AWS_REGION,
        endpoint_url=settings.AI_RESEARCH_REPLAY_DYNAMODB_ENDPOINT or None,
        config=config,
    )
    kms = boto3_client("kms", region_name=settings.AI_RESEARCH_REPLAY_AWS_REGION, config=config)
    return TrainingDataKeyReader(
        cast(DynamoReader, dynamo),
        cast(KmsReader, kms),
        settings.AI_RESEARCH_REPLAY_PRIVACY_TABLE,
        settings.AI_RESEARCH_REPLAY_KMS_KEY_ARN,
    )


def _encrypted_page_table(
    rows: list[_ScoredRow], reader: TrainingDataKeyReader, heartbeat: Callable[[], None]
) -> pa.Table:
    tables = []
    for start in range(0, len(rows), 256):
        tables.append(_encrypted_score_batch(rows[start : start + 256], reader))
        heartbeat()
    return pa.concat_tables(tables) if tables else pa.Table.from_pylist([], schema=_ENCRYPTED_SCORE_SCHEMA)


def _encrypted_score_batch(rows: list[_ScoredRow], reader: TrainingDataKeyReader) -> pa.Table:
    keys = reader.read([TrainingKeyLocation.session(team_id, session_id) for team_id, session_id, _, _ in rows])
    records = []
    for team_id, session_id, started_at, score in rows:
        key = keys.get(TrainingKeyLocation.session(team_id, session_id))
        if key is None:
            continue
        records.append(
            {
                "team_id": str(team_id),
                "session_id": session_id,
                "consent_granted_at": key.identity.consent_granted_at,
                "payload": key.encrypt(
                    "score",
                    json.dumps({"started_at": started_at.isoformat(), "surfacing_score": float(score)}).encode(),
                ),
            }
        )
    return pa.Table.from_pylist(records, schema=_ENCRYPTED_SCORE_SCHEMA)


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
    activity.heartbeat({"phase": "fetch", "day": spec.day, "chunk_id": spec.chunk_id})

    sinks = {False: io.BytesIO(), True: io.BytesIO()}
    writers = {
        raw: pq.ParquetWriter(sink, _ENCRYPTED_SCORE_SCHEMA if raw else _PARQUET_SCHEMA, compression="snappy")
        for raw, sink in sinks.items()
    }
    cursor = _FIRST_PAGE
    rows_total = 0
    secret: bytes | None = None
    reader: TrainingDataKeyReader | None = None
    try:
        while True:
            rows = await sync_to_async(_fetch_page, thread_sensitive=False)(spec, cursor)
            legacy_rows = [row for row in rows if not uses_raw_session_identifiers(row[1])]
            raw_rows = [row for row in rows if uses_raw_session_identifiers(row[1])]
            if legacy_rows:
                if secret is None:
                    try:
                        secret = await sync_to_async(resolve_pseudonym_key, thread_sensitive=False)()
                    except (PseudonymKeyNotConfiguredError, PseudonymKeyFingerprintMismatchError) as error:
                        raise ApplicationError(str(error), type=type(error).__name__, non_retryable=True) from error
                table = await sync_to_async(_page_table, thread_sensitive=False)(legacy_rows, secret)
                await sync_to_async(writers[False].write_table, thread_sensitive=False)(table)
                rows_total += table.num_rows
            if raw_rows and not spec.legacy_only:
                if reader is None:
                    reader = _score_key_reader()
                table = await sync_to_async(_encrypted_page_table, thread_sensitive=False)(
                    raw_rows,
                    reader,
                    lambda: activity.heartbeat({"phase": "encrypt", "day": spec.day, "chunk_id": spec.chunk_id}),
                )
                await sync_to_async(writers[True].write_table, thread_sensitive=False)(table)
                rows_total += table.num_rows
            if len(rows) < EXPORT_PAGE_MAX_ROWS:
                break
            cursor = (rows[-1][1], rows[-1][0])
            activity.heartbeat({"phase": "fetch", "day": spec.day, "chunk_id": spec.chunk_id, "rows": rows_total})
    finally:
        for writer in writers.values():
            writer.close()

    activity.heartbeat({"phase": "upload", "day": spec.day, "chunk_id": spec.chunk_id, "rows": rows_total})
    bytes_written = 0
    for raw_identifiers, sink in sinks.items():
        if raw_identifiers and spec.legacy_only:
            continue
        body = sink.getvalue()
        key = score_export_object_key(spec.day, spec.chunk_id, spec.of_chunks, raw_identifiers=raw_identifiers)
        await sync_to_async(_upload, thread_sensitive=False)(key, body)
        bytes_written += len(body)

    logger.info(
        "surfacing_score_export_sweep.partition_done",
        day=spec.day,
        chunk_id=spec.chunk_id,
        rows=rows_total,
        bytes=bytes_written,
    )
    return ExportPartitionResult(
        day=spec.day,
        chunk_id=spec.chunk_id,
        rows=rows_total,
        bytes_written=bytes_written,
        key=score_export_object_key(spec.day, spec.chunk_id, spec.of_chunks),
    )


ENCRYPTED_EXPORT_PAGE_ROWS = 4096


def _publish_encrypted_score_manifest(manifest: EncryptedScoreManifest) -> None:
    destination = score_export_destination()
    if destination is None:
        raise RuntimeError("ML score export destination not configured")
    partition = manifest.partition
    base = f"dt={partition.day}/part-{partition.chunk_id:04d}-of-{partition.of_chunks:04d}"
    manifest_key = f"{score_export_prefix()}/v2-manifests/{base}/{manifest.export_id}.json"
    prefix = f"{score_export_prefix()}/v2/{base}/export={manifest.export_id}/"
    client = boto3_client(
        "s3",
        region_name=destination.region,
        endpoint_url=destination.endpoint,
        aws_access_key_id=destination.access_key_id,
        aws_secret_access_key=destination.secret_access_key,
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 3}),
    )
    client.put_object(
        Bucket=destination.bucket,
        Key=manifest_key,
        ContentType="application/json",
        Body=json.dumps({"prefix": prefix, "pages": manifest.pages}).encode(),
    )


def _encrypted_query_parameters(spec: ExportPartitionSpec, cursor: ScoreCursor, page_size: int) -> dict[str, str | int]:
    return {
        "of_chunks": spec.of_chunks,
        "chunk_id": spec.chunk_id,
        "day_start": f"{spec.day} 00:00:00",
        "cursor_session_id": cursor.session_id,
        "cursor_team_id": cursor.team_id,
        "session_start_hex": f"{RAW_SESSION_IDENTIFIERS_START_MS:012x}",
        "page_size": page_size,
    }


def _plan_encrypted_score_ranges(inputs: EncryptedScorePlanInput) -> EncryptedScorePlan:
    rows = sync_execute(
        export_sql.plan_encrypted_score_ranges_sql(),
        _encrypted_query_parameters(inputs.partition, inputs.cursor, EXPORT_PAGE_MAX_ROWS),
        settings={
            "max_execution_time": CH_EXPORT_QUERY_TIMEOUT_S,
            "max_memory_usage": CH_EXPORT_QUERY_MAX_MEMORY_BYTES,
        },
    )
    boundaries = [
        ScoreCursor(team_id=rows[end - 1][0], session_id=rows[end - 1][1])
        for end in range(ENCRYPTED_EXPORT_PAGE_ROWS, len(rows) + 1, ENCRYPTED_EXPORT_PAGE_ROWS)
    ]
    if len(rows) % ENCRYPTED_EXPORT_PAGE_ROWS:
        boundaries.append(ScoreCursor(team_id=rows[-1][0], session_id=rows[-1][1]))
    return EncryptedScorePlan(boundaries=boundaries, has_more=len(rows) == EXPORT_PAGE_MAX_ROWS)


@activity.defn
async def plan_encrypted_score_ranges_activity(inputs: EncryptedScorePlanInput) -> EncryptedScorePlan:
    return await sync_to_async(_plan_encrypted_score_ranges, thread_sensitive=False)(inputs)


def _fetch_encrypted_score_range(page: EncryptedScorePage) -> list[_ScoredRow]:
    parameters = _encrypted_query_parameters(page.partition, page.cursor, ENCRYPTED_EXPORT_PAGE_ROWS)
    parameters.update(upper_team_id=page.upper.team_id, upper_session_id=page.upper.session_id)
    return cast(
        list[_ScoredRow],
        sync_execute(
            export_sql.fetch_encrypted_score_range_sql(),
            parameters,
            settings={
                "max_execution_time": CH_EXPORT_QUERY_TIMEOUT_S,
                "max_memory_usage": CH_EXPORT_QUERY_MAX_MEMORY_BYTES,
            },
        ),
    )


@activity.defn
async def publish_encrypted_score_manifest_activity(manifest: EncryptedScoreManifest) -> None:
    await sync_to_async(_publish_encrypted_score_manifest, thread_sensitive=False)(manifest)


@activity.defn
async def export_encrypted_scores_page_activity(page: EncryptedScorePage) -> EncryptedScorePageResult:
    activity.heartbeat({"phase": "fetch", "page": page.page})
    rows = await sync_to_async(_fetch_encrypted_score_range, thread_sensitive=False)(page)
    table = await sync_to_async(_encrypted_page_table, thread_sensitive=False)(
        rows, _score_key_reader(), lambda: activity.heartbeat({"phase": "encrypt", "page": page.page})
    )
    sink = io.BytesIO()
    pq.write_table(table, sink, compression="snappy")
    partition = page.partition
    key = (
        f"{score_export_prefix()}/v2/dt={partition.day}/"
        f"part-{partition.chunk_id:04d}-of-{partition.of_chunks:04d}/export={page.export_id}/page-{page.page:08d}.parquet"
    )
    body = sink.getvalue()
    await sync_to_async(_upload, thread_sensitive=False)(key, body)
    next_page = None
    if len(rows) == ENCRYPTED_EXPORT_PAGE_ROWS:
        cursor = ScoreCursor(team_id=rows[-1][0], session_id=rows[-1][1])
        if cursor != page.upper:
            next_page = replace(page, page=page.page + 1, cursor=cursor)
    return EncryptedScorePageResult(rows=table.num_rows, bytes_written=len(body), next_page=next_page)
