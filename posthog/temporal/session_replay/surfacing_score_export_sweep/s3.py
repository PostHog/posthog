"""Destination config, object-key layout, and upload helper — same
`{prefix}/dt=.../part-*.parquet` layout as the ML mirror's Parquet store, but
with deterministic part names so re-runs overwrite.

The destination is its own `SESSION_RECORDING_ML_SCORE_EXPORT_S3_*` config
with NO fallback to the `SESSION_RECORDING_V2_S3_*` replay-store settings: on
the shared Temporal worker those point at the production replay bucket, and
the mirror only reuses them safely because it runs as a dedicated deployment.
Unset bucket → the sweep is disabled."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    DEFAULT_SCORE_EXPORT_PREFIX,
    SCORE_EXPORT_PREFIX_ENV_VAR,
)

S3_BUCKET_ENV_VAR = "SESSION_RECORDING_ML_SCORE_EXPORT_S3_BUCKET"
S3_REGION_ENV_VAR = "SESSION_RECORDING_ML_SCORE_EXPORT_S3_REGION"
S3_ENDPOINT_ENV_VAR = "SESSION_RECORDING_ML_SCORE_EXPORT_S3_ENDPOINT"
S3_ACCESS_KEY_ID_ENV_VAR = "SESSION_RECORDING_ML_SCORE_EXPORT_S3_ACCESS_KEY_ID"
S3_SECRET_ACCESS_KEY_ENV_VAR = "SESSION_RECORDING_ML_SCORE_EXPORT_S3_SECRET_ACCESS_KEY"

PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"


@dataclass(frozen=True)
class ScoreExportDestination:
    bucket: str
    region: str
    # None → default AWS endpoint; keys None → ambient credential chain (IRSA/instance profile).
    endpoint: str | None
    access_key_id: str | None
    secret_access_key: str | None


def score_export_destination() -> ScoreExportDestination | None:
    bucket = os.environ.get(S3_BUCKET_ENV_VAR, "")
    if not bucket:
        return None
    return ScoreExportDestination(
        bucket=bucket,
        region=os.environ.get(S3_REGION_ENV_VAR, "us-east-1"),
        endpoint=os.environ.get(S3_ENDPOINT_ENV_VAR) or None,
        access_key_id=os.environ.get(S3_ACCESS_KEY_ID_ENV_VAR) or None,
        secret_access_key=os.environ.get(S3_SECRET_ACCESS_KEY_ENV_VAR) or None,
    )


def score_export_prefix() -> str:
    return os.environ.get(SCORE_EXPORT_PREFIX_ENV_VAR, DEFAULT_SCORE_EXPORT_PREFIX)


def score_export_object_key(day: str, chunk_id: int, of_chunks: int) -> str:
    return f"{score_export_prefix()}/dt={day}/part-{chunk_id:04d}-of-{of_chunks:04d}.parquet"


def upload_parquet(s3_client: Any, *, bucket: str, key: str, body: bytes) -> None:
    s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=PARQUET_CONTENT_TYPE)
