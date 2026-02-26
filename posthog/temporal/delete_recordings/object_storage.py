"""S3-backed chunked storage for session ID deletion workflows.

Avoids exceeding Temporal's ~2MB payload limit by storing session IDs
as chunked files in S3 instead of inline in the workflow input.

Write path (sync, from Django admin): uses posthog.storage.object_storage.write()
Read/delete path (async, from Temporal activities): uses aioboto3
"""

import math
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from itertools import batched

from django.conf import settings

import aioboto3
from botocore.client import Config

from posthog.storage import object_storage

logger = logging.getLogger(__name__)

STORAGE_KEY_PREFIX = "deletion-inputs"


def generate_prefix(workflow_id: str) -> str:
    return f"{STORAGE_KEY_PREFIX}/{workflow_id}/"


def generate_chunk_key(prefix: str, chunk_index: int) -> str:
    return f"{prefix}chunk-{chunk_index:04d}.csv"


def store_session_id_chunks(
    workflow_id: str,
    session_ids: list[str],
    chunk_size: int = 10_000,
) -> tuple[str, int]:
    """Upload session IDs as chunked CSV files to S3.

    Returns (s3_prefix, total_chunks).
    """
    prefix = generate_prefix(workflow_id)
    total_chunks = math.ceil(len(session_ids) / chunk_size)

    for i, chunk in enumerate(batched(session_ids, chunk_size)):
        key = generate_chunk_key(prefix, i)
        content = "\n".join(chunk)
        object_storage.write(key, content)

    return prefix, total_chunks


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


async def load_session_id_chunk(prefix: str, chunk_index: int) -> list[str]:
    key = generate_chunk_key(prefix, chunk_index)
    async with _s3_client() as client:
        try:
            response = await client.get_object(
                Bucket=settings.OBJECT_STORAGE_BUCKET,
                Key=key,
            )
        except client.exceptions.NoSuchKey:
            raise ValueError(f"Chunk file not found: {key}")
        raw = await response["Body"].read()

    return [line for line in raw.decode("utf-8").split("\n") if line]


async def delete_session_id_chunks(prefix: str, total_chunks: int) -> None:
    async with _s3_client() as client:
        for i in range(total_chunks):
            key = generate_chunk_key(prefix, i)
            try:
                await client.delete_object(
                    Bucket=settings.OBJECT_STORAGE_BUCKET,
                    Key=key,
                )
            except Exception:
                logger.warning("Failed to delete chunk %s, orphaned object may remain", key, exc_info=True)
