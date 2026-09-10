"""Destination config, object-key layout, and upload helper — same
`{prefix}/v2/dt=.../part-*.parquet` layout as the ML mirror's Parquet store, but
with deterministic part names so re-runs overwrite.

The destination is its own `AI_RESEARCH_REPLAY_SCORE_EXPORT_S3_*` config
with NO fallback to the `SESSION_RECORDING_V2_S3_*` replay-store settings: on
the shared Temporal worker those point at the production replay bucket, and
the mirror only reuses them safely because it runs as a dedicated deployment.
Unset bucket → the sweep is disabled."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    DEFAULT_SCORE_EXPORT_PREFIX,
    SCORE_EXPORT_PREFIX_ENV_VAR,
)
from posthog.temporal.session_replay.surfacing_score_export_sweep.env import get_ai_research_replay_env

S3_BUCKET_ENV_VAR = "AI_RESEARCH_REPLAY_SCORE_EXPORT_S3_BUCKET"
S3_REGION_ENV_VAR = "AI_RESEARCH_REPLAY_SCORE_EXPORT_S3_REGION"
S3_ENDPOINT_ENV_VAR = "AI_RESEARCH_REPLAY_SCORE_EXPORT_S3_ENDPOINT"
S3_ACCESS_KEY_ID_ENV_VAR = "AI_RESEARCH_REPLAY_SCORE_EXPORT_S3_ACCESS_KEY_ID"
S3_SECRET_ACCESS_KEY_ENV_VAR = "AI_RESEARCH_REPLAY_SCORE_EXPORT_S3_SECRET_ACCESS_KEY"

PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"


@dataclass(frozen=True)
class ScoreExportDestination:
    bucket: str
    region: str
    # None → default AWS endpoint; keys None → ambient credential chain (IRSA/instance profile).
    endpoint: str | None
    access_key_id: str | None
    secret_access_key: str | None = field(repr=False)


def score_export_destination() -> ScoreExportDestination | None:
    bucket = get_ai_research_replay_env(S3_BUCKET_ENV_VAR, "")
    if not bucket:
        return None
    return ScoreExportDestination(
        bucket=bucket,
        region=get_ai_research_replay_env(S3_REGION_ENV_VAR, "us-east-1"),
        endpoint=get_ai_research_replay_env(S3_ENDPOINT_ENV_VAR) or None,
        access_key_id=get_ai_research_replay_env(S3_ACCESS_KEY_ID_ENV_VAR) or None,
        secret_access_key=get_ai_research_replay_env(S3_SECRET_ACCESS_KEY_ENV_VAR) or None,
    )


def score_export_prefix() -> str:
    return get_ai_research_replay_env(SCORE_EXPORT_PREFIX_ENV_VAR, DEFAULT_SCORE_EXPORT_PREFIX)


def score_export_object_key(day: str, chunk_id: int, of_chunks: int, *, raw_identifiers: bool = True) -> str:
    prefix = f"{score_export_prefix()}/v2" if raw_identifiers else score_export_prefix()
    return f"{prefix}/dt={day}/part-{chunk_id:04d}-of-{of_chunks:04d}.parquet"


def upload_parquet(s3_client: Any, *, bucket: str, key: str, body: bytes) -> None:
    s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=PARQUET_CONTENT_TYPE)
