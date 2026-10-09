import json
from time import monotonic

from django.utils import timezone

from posthog.models.integration import GitHubIntegration, Integration
from posthog.redis import get_client

REFRESH_CHUNK_SECONDS = 60
CHECKPOINT_TTL_SECONDS = 60 * 60


def refresh_repository_cache_chunk(github: GitHubIntegration) -> bool:
    """Checkpoint pages under the caller's lease; return whether another chunk is needed."""
    integration = github.integration
    installation_id = integration.integration_id
    updated_at = integration.repository_cache_updated_at
    revision = json.dumps([installation_id, updated_at.isoformat() if updated_at else None])
    checkpoint_key = f"github:repository_cache_refresh:{integration.team_id}:{integration.id}:pages"
    redis = get_client()
    deadline = monotonic() + REFRESH_CHUNK_SECONDS
    stored_revision, next_page, complete = redis.hmget(checkpoint_key, ["revision", "next_page", "complete"])

    if stored_revision not in (revision, revision.encode()):
        with redis.pipeline(transaction=True) as pipeline:
            pipeline.delete(checkpoint_key)
            pipeline.hset(checkpoint_key, mapping={"revision": revision, "next_page": 1, "complete": 0})
            pipeline.expire(checkpoint_key, CHECKPOINT_TTL_SECONDS)
            pipeline.execute()
        next_page, complete = 1, 0

    page = int(next_page or 1)
    while complete not in (b"1", "1", 1):
        if monotonic() >= deadline:
            return True

        repositories, has_more = github.list_repositories(page=page, per_page=100)
        complete = int(not has_more or not repositories)
        # Commit the page and its cursor together so a killed worker cannot skip or duplicate a page.
        with redis.pipeline(transaction=True) as pipeline:
            pipeline.hset(
                checkpoint_key,
                mapping={f"page:{page}": json.dumps(repositories), "next_page": page + 1, "complete": complete},
            )
            pipeline.expire(checkpoint_key, CHECKPOINT_TTL_SECONDS)
            pipeline.execute()
        page += 1

    pages = redis.hmget(checkpoint_key, [f"page:{number}" for number in range(1, page)])
    repositories = [repository for payload in pages for repository in json.loads(payload)]
    # Publish only a complete scan, without overwriting a reconnect or a newer cache refresh.
    Integration.objects.filter(
        id=integration.id,
        team_id=integration.team_id,
        kind="github",
        integration_id=installation_id,
        repository_cache_updated_at=updated_at,
    ).update(repository_cache=repositories, repository_cache_updated_at=timezone.now())
    redis.delete(checkpoint_key)
    return False
