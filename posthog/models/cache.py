from typing import Optional
from django.core import serializers
from django.db.models import QuerySet, Manager
import posthoganalytics
from prometheus_client import Counter

from posthog.exceptions_capture import capture_exception
from posthog.git import get_git_commit_short
from posthog.redis import get_client
from posthog.settings import TEST

TEST_OVERRIDE = False

DATABASE_CACHE_COUNTER = Counter(
    "posthog_get_model_cache",
    "Metric tracking whether a database query was fetched from cache or not",
    labelnames=["result", "model"],
)

DATABASE_INVALIDATION_COUNTER = Counter(
    "posthog_invalidate_model_cache",
    "Metric tracking whether a database query was invalidated",
    labelnames=["model"],
)


# temporary for rollout purposes
def is_cache_enabled(team_id: int) -> bool:
    """
    Use the hogql database cache.
    """
    from posthog.models.team import Team

    if not Team.objects.filter(id=team_id).exists():
        return False

    team = Team.objects.get(id=team_id)

    return posthoganalytics.feature_enabled(
        "hogql-database-cache",
        str(team.uuid),
        groups={
            "organization": str(team.organization_id),
            "project": str(team.id),
        },
        group_properties={
            "organization": {
                "id": str(team.organization_id),
            },
            "project": {
                "id": str(team.id),
            },
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


class CachedQuerySet(QuerySet):
    def get_commit_cache_key(self, team_id: int, key_prefix: Optional[str] = None) -> str:
        current_sha = get_git_commit_short()
        key = f"{team_id}:{current_sha}:{self.model.__name__}"

        if key_prefix:
            key = f"{key_prefix}:{key}"

        # cache key based on sha to invalidate cache on deploys in case of migrations
        return key

    def fetch_cached(self, team_id: int, timeout: int = 600, key_prefix: Optional[str] = None):
        # we want the behavior for tests to be unaffected unless specifically testing this logic
        testing = TEST and not TEST_OVERRIDE

        if is_cache_enabled(team_id) and not testing:
            try:
                redis_client = get_client()
                key = self.get_commit_cache_key(team_id=team_id, key_prefix=key_prefix)

                data = redis_client.get(key)
                if data is not None:
                    DATABASE_CACHE_COUNTER.labels(result="hit_redis", model=self.model.__name__).inc()
                    return [deserialized.object for deserialized in serializers.deserialize("json", data)]

                data = serializers.serialize("json", self)

                redis_client.set(key, data, ex=timeout)
                DATABASE_CACHE_COUNTER.labels(result="hit_db", model=self.model.__name__).inc()
            except Exception as e:
                capture_exception(e)
                DATABASE_CACHE_COUNTER.labels(result="error", model=self.model.__name__).inc()

        return list(self)

    def invalidate_cache(self, team_id: int, key_prefix: Optional[str] = None):
        try:
            redis_client = get_client()
            key = self.get_commit_cache_key(team_id=team_id, key_prefix=key_prefix)
            deleted_count = redis_client.delete(key)
            if deleted_count > 0:
                DATABASE_INVALIDATION_COUNTER.labels(model=self.model.__name__).inc()
        except Exception as e:
            capture_exception(e)


class CacheManager(Manager.from_queryset(CachedQuerySet)):  # type: ignore
    pass
