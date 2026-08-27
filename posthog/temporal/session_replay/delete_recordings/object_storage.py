"""S3-backed chunked storage for session ID deletion workflows.

Avoids exceeding Temporal's ~2MB payload limit by storing session IDs
as chunked files in S3 instead of inline in the workflow input.
"""

import math
import asyncio
import logging
from itertools import batched

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

    for i, chunk in enumerate(batched(session_ids, chunk_size, strict=False)):
        key = generate_chunk_key(prefix, i)
        content = "\n".join(chunk)
        object_storage.write(key, content)

    return prefix, total_chunks


async def load_session_id_chunk(prefix: str, chunk_index: int) -> list[str]:
    key = generate_chunk_key(prefix, chunk_index)
    # The shared object storage client is synchronous, so run it off the event loop.
    raw = await asyncio.to_thread(object_storage.read_bytes, key, missing_ok=True)
    if raw is None:
        raise ValueError(f"Chunk file not found: {key}")

    return [line for line in raw.decode("utf-8").split("\n") if line]


async def delete_session_id_chunks(prefix: str, total_chunks: int) -> None:
    keys = [generate_chunk_key(prefix, i) for i in range(total_chunks)]
    failed_keys = await asyncio.to_thread(object_storage.delete_objects, keys)
    if failed_keys:
        logger.warning("Failed to delete chunks %s, orphaned objects may remain", failed_keys)
