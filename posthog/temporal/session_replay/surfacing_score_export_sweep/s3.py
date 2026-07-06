"""Object-key layout and upload helper for the score export dataset.

Mirrors the ML mirror's Parquet store (`block-metadata-parquet-store.ts`)
layout — `{prefix}/dt=YYYY-MM-DD/part-*.parquet` in the same bucket — except
the part name is deterministic per (chunk, of_chunks) instead of
per-writer-unique, because re-runs are meant to overwrite.
"""

from __future__ import annotations

import os
from typing import Any

from posthog.temporal.session_replay.surfacing_score_export_sweep.constants import (
    DEFAULT_SCORE_EXPORT_PREFIX,
    SCORE_EXPORT_PREFIX_ENV_VAR,
)

PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"


def score_export_prefix() -> str:
    return os.environ.get(SCORE_EXPORT_PREFIX_ENV_VAR, DEFAULT_SCORE_EXPORT_PREFIX)


def score_export_object_key(day: str, chunk_id: int, of_chunks: int) -> str:
    return f"{score_export_prefix()}/dt={day}/part-{chunk_id:04d}-of-{of_chunks:04d}.parquet"


def upload_parquet(s3_client: Any, *, bucket: str, key: str, body: bytes) -> None:
    s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=PARQUET_CONTENT_TYPE)
