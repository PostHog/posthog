"""Object storage for fetch_segments payload to avoid exceeding Temporal's 2 MB limit.

Uses S3-compatible object storage with gzip compression. The bucket should have
a 24h lifecycle rule for automatic cleanup of stale data.
"""

import gzip
import json
import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from django.conf import settings

import aioboto3
from botocore.client import Config

from posthog.temporal.ai.video_segment_clustering.models import VideoSegment

STORAGE_KEY_PREFIX = "video_segment_clustering"


def generate_storage_key(team_id: int, workflow_run_id: str, *, name: str) -> str:
    return f"{STORAGE_KEY_PREFIX}/team-{team_id}/{workflow_run_id}/{name}.json.gz"


@asynccontextmanager
async def _s3_client() -> AsyncIterator:
    session = aioboto3.Session()
    async with session.client(  # type: ignore[call-overload]
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        config=Config(
            signature_version="s3v4",
            connect_timeout=1,
            retries={"max_attempts": 1},
        ),
        region_name=settings.OBJECT_STORAGE_REGION,
    ) as client:
        yield client


async def store_fetch_result(
    key: str,
    segments: list[VideoSegment],
    distinct_ids: list[str],
) -> None:
    payload = {
        "segments": [dataclasses.asdict(s) for s in segments],
        "distinct_ids": distinct_ids,
    }
    content = gzip.compress(json.dumps(payload).encode("utf-8"))
    async with _s3_client() as client:
        await client.put_object(
            Bucket=settings.VIDEO_SEGMENT_CLUSTERING_S3_BUCKET,
            Key=key,
            Body=content,
        )


async def load_fetch_result(
    key: str,
) -> tuple[list[VideoSegment], list[str]]:
    """Load fetch result from object storage. Raises ValueError if key not found."""
    async with _s3_client() as client:
        try:
            response = await client.get_object(
                Bucket=settings.VIDEO_SEGMENT_CLUSTERING_S3_BUCKET,
                Key=key,
            )
        except client.exceptions.NoSuchKey:
            raise ValueError(f"Object storage key {key} not found")
        raw = await response["Body"].read()

    data = json.loads(gzip.decompress(raw).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Object storage key {key} contains invalid data type: {type(data)}")
    if "document_ids" in data:
        raise ValueError(f"Old storage format detected for key {key}. Please re-run workflow.")
    if "segments" not in data or "distinct_ids" not in data:
        raise ValueError(f"Object storage key {key} missing required keys")
    segments = [VideoSegment(**s) for s in data["segments"]]
    return segments, data["distinct_ids"]
