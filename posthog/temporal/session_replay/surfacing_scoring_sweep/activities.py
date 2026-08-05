"""Temporal activities for the session surfacing scoring pipeline.

Two activities:
    * `list_chunks_activity` — runs once per workflow tick to gauge backlog
      and emit deterministic chunk specs. Cheap.
    * `score_chunk_activity` — runs once per chunk; does fetch-features
      (CH SELECT) → predict (XGBoost) → publish-scores (Kafka) end to end.
      The work for each chunk is fully self-contained: no Redis, no S3, no
      cross-activity state.

Score writeback piggybacks on the existing `KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS`
topic + `session_replay_events_mv` — same pattern as the AI-summary writeback
in `posthog.temporal.session_replay.session_summary.activities.video_based.
a7d_tag_and_highlight_session`. We send a partial-row Kafka message with
identity values for every non-score column; the MV's `max(surfacing_score)`
aggregation merges the score onto the real session row in the AggregatingMergeTree.

Idempotency guarantees:
    * Hash partitioning (`cityHash64(session_id) %% of_chunks = chunk_id`)
      gives every session exactly one bucket.
    * The CH SELECT filters `HAVING max(surfacing_score) IS NULL` —
      sessions already scored in a previous attempt are skipped naturally.
    * `surfacing_score` is `SimpleAggregateFunction(max, ...)` and the
      Temporal pipeline only ever writes a single score per session, so even if
      Kafka redelivers a message after a worker crash the merge is a no-op.
    * Re-running a failed `score_chunk_activity` thus never double-scores
      a session and never burns the same CPU twice on already-written rows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import numpy as np
import pandas as pd
import structlog
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.temporal.session_replay.surfacing_scoring_sweep import sql as surfacing_scoring_sweep_sql
from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import (
    CH_FEATURE_QUERY_MAX_MEMORY_BYTES,
    CH_FEATURE_QUERY_TIMEOUT_S,
    DEFAULT_OF_CHUNKS,
    KAFKA_PRODUCE_FLUSH_TIMEOUT_S,
    SCORE_LOOKBACK_DAYS,
    TARGET_CHUNK_SIZE,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.features import (
    ID_COLUMNS,
    MODEL_FEATURE_SCHEMA_VERSION,
    FeatureValidationError,
    out_of_contract_row_mask,
    validate_features,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.metrics import record_backlog_estimate
from posthog.temporal.session_replay.surfacing_scoring_sweep.scorer import get_feature_names, predict
from posthog.temporal.session_replay.surfacing_scoring_sweep.types import (
    ChunkResult,
    ChunkSpec,
    ListChunksResult,
    ScoreSessionsBatchInputs,
)

logger = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# list_chunks_activity                                                         #
# --------------------------------------------------------------------------- #


def _count_unscored_in_one_bucket(lookback_days: int, of_chunks: int) -> int:
    rows = cast(
        list[tuple[int]],
        sync_execute(
            surfacing_scoring_sweep_sql.count_unscored_sql(),
            {"lookback_days": lookback_days, "of_chunks": of_chunks},
            settings={
                "max_execution_time": CH_FEATURE_QUERY_TIMEOUT_S,
                "max_memory_usage": CH_FEATURE_QUERY_MAX_MEMORY_BYTES,
            },
        ),
    )
    return int(rows[0][0]) if rows else 0


@activity.defn
async def list_chunks_activity(_inputs: ScoreSessionsBatchInputs) -> ListChunksResult:
    lookback_days = SCORE_LOOKBACK_DAYS
    of_chunks = DEFAULT_OF_CHUNKS
    chunk_size = TARGET_CHUNK_SIZE

    sampled = await sync_to_async(_count_unscored_in_one_bucket, thread_sensitive=False)(lookback_days, of_chunks)
    estimated_total = sampled * of_chunks
    record_backlog_estimate(estimated_total)

    chunks = [
        ChunkSpec(
            chunk_id=i,
            of_chunks=of_chunks,
            chunk_size=chunk_size,
            lookback_days=lookback_days,
        )
        for i in range(of_chunks)
    ]
    logger.info(
        "surfacing_scoring_sweep.list_chunks.dispatched",
        of_chunks=of_chunks,
        chunk_size=chunk_size,
        estimated_unscored_sessions=estimated_total,
    )
    return ListChunksResult(chunks=chunks, estimated_unscored_sessions=estimated_total)


# --------------------------------------------------------------------------- #
# score_chunk_activity                                                         #
# --------------------------------------------------------------------------- #


def _build_features_dataframe(rows: list[tuple], columns: list[str]) -> pd.DataFrame:
    """Coerce all-NULL feature columns (driver returns all-`None` → pandas `object`) to float so they pass `validate_features`; typed columns are left untouched so genuine dtype drift still fails the chunk."""
    df = pd.DataFrame(rows, columns=pd.Index(columns))
    for col in df.columns:
        if col not in ID_COLUMNS and df[col].dtype == object and df[col].isna().all():
            df[col] = df[col].astype(float)
    return df


def _fetch_features_dataframe(spec: ChunkSpec) -> pd.DataFrame:
    """Run the feature SELECT and return a pandas DataFrame."""
    result = cast(
        tuple[list[tuple], list[tuple[str, str]]],
        sync_execute(
            surfacing_scoring_sweep_sql.fetch_features_sql(),
            {
                "lookback_days": spec.lookback_days,
                "of_chunks": spec.of_chunks,
                "chunk_id": spec.chunk_id,
                "chunk_size": spec.chunk_size,
            },
            settings={
                "max_execution_time": CH_FEATURE_QUERY_TIMEOUT_S,
                "max_memory_usage": CH_FEATURE_QUERY_MAX_MEMORY_BYTES,
            },
            with_column_types=True,
        ),
    )
    rows, column_metadata = result
    columns = [name for name, _type in column_metadata]
    return _build_features_dataframe(rows, columns)


def _build_partial_row(
    *,
    team_id: int,
    session_id: str,
    distinct_id: str,
    min_first_timestamp: datetime,
    score: float,
) -> dict[str, Any]:
    """Identity-value Kafka payload that merges cleanly into session_replay_events.

    Mirrors `tag_and_highlight_session_activity._produce_to_kafka`:

    * Timestamps use `min_first_timestamp + 1µs` so min(first_timestamp),
      argMin(first_url, first_timestamp), and max(last_timestamp) all keep
      the real session's values — never the partial row's. Using now() would
      shift max_last_timestamp forward by however long the scorer takes.
    * `block_url=None` is critical: groupArray(block_url) drops nulls. An empty
      string would pollute `block_urls` and break the length-match check in
      listBlocks downstream.
    * `first_url=None`, `snapshot_*=None`: argMin* drops nulls, so the real
      session's first_url survives even though we wrote with an "earlier"
      timestamp.
    * `distinct_id` MUST be the session's real distinct_id — it's the
      Distributed sharding key (`sipHash64(distinct_id)`). A wrong value would
      route this partial row to a different shard than the real session rows,
      forcing every read on this session into a cross-shard merge.
    """
    ts = min_first_timestamp + timedelta(microseconds=1)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    partial_ts = format_clickhouse_timestamp(ts)
    return {
        "session_id": session_id,
        "team_id": team_id,
        "distinct_id": distinct_id,
        "first_timestamp": partial_ts,
        "last_timestamp": partial_ts,
        "block_url": None,
        "first_url": None,
        "urls": [],
        "click_count": 0,
        "keypress_count": 0,
        "mouse_activity_count": 0,
        "active_milliseconds": 0,
        "console_log_count": 0,
        "console_warn_count": 0,
        "console_error_count": 0,
        "size": 0,
        "event_count": 0,
        "message_count": 0,
        "snapshot_source": None,
        "snapshot_library": None,
        "retention_period_days": None,
        "is_deleted": 0,
        "ai_tags_fixed": [],
        "ai_tags_freeform": [],
        "ai_highlighted": 0,
        "surfacing_score": score,
    }


def _publish_scores(df: pd.DataFrame, scores: np.ndarray) -> int:
    """Produce one Kafka message per scored session and flush before returning.

    Rides the same `session_replay_events_mv` as ingestion, whose
    `max(surfacing_score)` merges the score onto the real session row.

    Per-row produce keeps retries simple: a mid-loop crash just re-runs the
    chunk, and already-produced sessions are either skipped next tick (once CH
    has consumed, via `HAVING max(surfacing_score) IS NULL`) or harmlessly
    re-merged by the `max`-typed column.

    Returns the row count handed off to the producer (after flush), which
    `score_chunk_activity` reports as `ChunkResult.scored`.
    """
    if df.empty:
        return 0

    producer = get_producer(topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS)
    team_ids = df["team_id"].to_numpy()
    session_ids = df["session_id"].to_numpy()
    distinct_ids = df["distinct_id"].to_numpy()
    min_first_timestamps = df["min_first_timestamp"].to_numpy()
    rows_published = 0
    for team_id, session_id, distinct_id, min_first_timestamp, score in zip(
        team_ids, session_ids, distinct_ids, min_first_timestamps, scores, strict=True
    ):
        producer.produce(
            topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
            data=_build_partial_row(
                team_id=int(team_id),
                session_id=str(session_id),
                distinct_id=str(distinct_id),
                min_first_timestamp=pd.Timestamp(min_first_timestamp).to_pydatetime(),
                score=float(score),
            ),
        )
        rows_published += 1

    # Don't ack until librdkafka has flushed.
    remaining = producer.flush(timeout=KAFKA_PRODUCE_FLUSH_TIMEOUT_S)
    if remaining > 0:
        raise RuntimeError(
            f"{remaining} surfacing_score message(s) not delivered within "
            f"{KAFKA_PRODUCE_FLUSH_TIMEOUT_S}s — chunk will retry"
        )

    return rows_published


@activity.defn
async def score_chunk_activity(spec: ChunkSpec) -> ChunkResult:
    """Score one hash-partitioned chunk of unscored sessions, end to end."""
    activity.heartbeat({"phase": "fetch", "chunk_id": spec.chunk_id})
    df = await sync_to_async(_fetch_features_dataframe, thread_sensitive=False)(spec)

    # Sessions pulled from ClickHouse for this chunk, before any out-of-contract drop.
    fetched = len(df)

    if df.empty:
        return ChunkResult(chunk_id=spec.chunk_id, scored=0, fetched=fetched)

    feature_names = await sync_to_async(get_feature_names, thread_sensitive=False)()

    activity.logger.info(
        "surfacing_scoring_sweep.fetched",
        chunk_id=spec.chunk_id,
        rows=len(df),
        feature_schema_version=MODEL_FEATURE_SCHEMA_VERSION,
        feature_count=len(feature_names),
    )

    try:
        validate_features(df, feature_names=feature_names)
    except FeatureValidationError as e:
        raise ApplicationError(
            f"feature validation failed for chunk {spec.chunk_id}: {e}",
            type="FeatureValidationError",
            non_retryable=True,
        ) from e

    # Value-level violations are data-driven (replay payloads are
    # client-controlled), so drop just the offending sessions — failing the
    # chunk would deterministically re-fail this hash bucket every tick.
    bad_rows = out_of_contract_row_mask(df, feature_names=feature_names)
    if bad_rows.any():
        activity.logger.warning(
            "surfacing_scoring_sweep.rows_out_of_contract",
            chunk_id=spec.chunk_id,
            dropped=int(bad_rows.sum()),
            rows=len(df),
        )
        df = df.loc[~bad_rows]
        if df.empty:
            return ChunkResult(chunk_id=spec.chunk_id, scored=0, fetched=fetched)

    activity.heartbeat({"phase": "predict", "chunk_id": spec.chunk_id, "rows": len(df)})
    scores = await sync_to_async(predict, thread_sensitive=False)(df)

    activity.heartbeat({"phase": "publish", "chunk_id": spec.chunk_id, "rows": len(df)})
    published = await sync_to_async(_publish_scores, thread_sensitive=False)(df, scores)

    activity.logger.info(
        "surfacing_scoring_sweep.chunk_done",
        chunk_id=spec.chunk_id,
        scored=published,
        fetched=fetched,
        feature_count=len(feature_names),
    )
    return ChunkResult(chunk_id=spec.chunk_id, scored=published, fetched=fetched)
