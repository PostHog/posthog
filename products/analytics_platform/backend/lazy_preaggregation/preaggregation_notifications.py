import uuid

import redis as redis_lib

from posthog import redis
from posthog.clickhouse.client.execute_async import QueryStatusManager

PREAGG_JOB_CHANNEL_PREFIX = "preagg:job:"
PREAGG_CH_STARTED_PREFIX = "preagg:ch_started:"
CH_STARTED_TTL_SECONDS = 15 * 60  # 15 minutes


def job_channel(job_id: uuid.UUID) -> str:
    return f"{PREAGG_JOB_CHANNEL_PREFIX}{job_id}"


def publish_job_completion(job_id: uuid.UUID, status: str) -> None:
    """Publish completion notification. Called after job.save() sets terminal status."""
    client = redis.get_client()
    client.publish(job_channel(job_id), status)


def subscribe_to_jobs(job_ids: list[uuid.UUID]) -> redis_lib.client.PubSub:
    """Create pubsub subscription for multiple job channels."""
    client = redis.get_client()
    pubsub = client.pubsub()
    for job_id in job_ids:
        pubsub.subscribe(job_channel(job_id))
    return pubsub


def set_ch_query_started(job_id: uuid.UUID) -> None:
    """Mark that the CH INSERT has begun. Key: preagg:ch_started:{job_id}, TTL 15min.

    Uses SET NX — fails if the key already exists, since each job ID must map
    to exactly one INSERT. A duplicate means a bug (job ID reuse).
    """
    client = redis.get_client()
    was_set = client.set(f"{PREAGG_CH_STARTED_PREFIX}{job_id}", "1", ex=CH_STARTED_TTL_SECONDS, nx=True)
    if not was_set:
        raise RuntimeError(f"CH query already started for job {job_id} — job ID reuse is a bug")


def has_ch_query_started(job_id: uuid.UUID) -> bool:
    """Check if the CH INSERT marker exists."""
    client = redis.get_client()
    return client.exists(f"{PREAGG_CH_STARTED_PREFIX}{job_id}") == 1


def is_ch_query_alive(team_id: int, job_id: uuid.UUID) -> bool:
    """Check if poll_query_performance has recently seen this query.
    Uses the heartbeat key set by QueryStatusManager."""
    manager = QueryStatusManager(str(job_id), team_id)
    return manager.redis_client.exists(manager.heartbeat_key) == 1
