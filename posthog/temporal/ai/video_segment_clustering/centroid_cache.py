"""Redis-based centroid cache for video segment clustering workflow.

Uses NumPy binary format (float32) for efficient storage:
- JSON: 3072 floats × ~20 bytes = 62KB per centroid
- Binary float32: 3072 × 4 bytes = 12KB per centroid (5x smaller)
"""

import numpy as np
from temporalio import activity

from posthog.redis import get_async_client

CENTROID_CACHE_TTL_SECONDS = 4 * 60 * 60  # 4 hours
EMBEDDING_DIM = 3072


def _cache_key(workflow_id: str, suffix: str) -> str:
    return f"video_segment_clustering:centroids:{workflow_id}:{suffix}"


async def store_centroids(
    workflow_id: str,
    centroids: dict[int, list[float]],
    ttl: int = CENTROID_CACHE_TTL_SECONDS,
) -> None:
    """Store cluster centroids in Redis using NumPy binary format."""
    if not centroids:
        return

    redis_client = get_async_client()

    # Store as two arrays: cluster_ids (int32) and embeddings (float32)
    cluster_ids = np.array(list(centroids.keys()), dtype=np.int32)
    embeddings = np.array(list(centroids.values()), dtype=np.float32)

    pipeline = redis_client.pipeline(transaction=True)
    pipeline.setex(_cache_key(workflow_id, "ids"), ttl, cluster_ids.tobytes())
    pipeline.setex(_cache_key(workflow_id, "embeddings"), ttl, embeddings.tobytes())
    await pipeline.execute()


async def get_centroids(workflow_id: str) -> dict[int, list[float]] | None:
    """Retrieve cluster centroids from Redis."""
    redis_client = get_async_client()

    ids_data = await redis_client.get(_cache_key(workflow_id, "ids"))
    emb_data = await redis_client.get(_cache_key(workflow_id, "embeddings"))

    if not ids_data or not emb_data:
        return None

    cluster_ids = np.frombuffer(ids_data, dtype=np.int32)
    embeddings = np.frombuffer(emb_data, dtype=np.float32).reshape(-1, EMBEDDING_DIM)

    return {int(cid): emb.tolist() for cid, emb in zip(cluster_ids, embeddings)}


async def delete_centroids(workflow_id: str) -> None:
    """Delete centroid cache for a workflow."""
    redis_client = get_async_client()
    await redis_client.delete(_cache_key(workflow_id, "ids"), _cache_key(workflow_id, "embeddings"))


def get_workflow_id_from_activity() -> str:
    """Get workflow ID from within an activity context."""
    return activity.info().workflow_id
