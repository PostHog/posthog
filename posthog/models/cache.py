import hashlib
from typing import TYPE_CHECKING, Optional
from django.core import serializers
from django.db.models import QuerySet, Manager
import posthoganalytics
from prometheus_client import Counter

from posthog.exceptions_capture import capture_exception
from posthog.git import get_git_commit_short
from posthog.redis import get_client
from posthog.settings import TEST

if TYPE_CHECKING:
    from posthog.models import Team


DATABASE_CACHE_HIT_COUNTER = Counter(
    "posthog_model_cache_hit",
    "Metric tracking when a database query was fetched from cache",
    labelnames=["model"],
)

DATABASE_CACHE_MISS_COUNTER = Counter(
    "posthog_model_cache_miss",
    "Metric tracking when a database query was not fetched from cache",
    labelnames=["model"],
)

DATABASE_INVALIDATION_COUNTER = Counter(
    "posthog_model_cache_bust",
    "Metric tracking when a database query was invalidated",
    labelnames=["model"],
)

CACHE_TEST_OVERRIDE = False


# temporary for rollout purposes
def is_cache_enabled(team: "Team") -> bool:
    """
    Use the hogql database cache.
    """

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
    def get_commit_cache_hash_key(self, team_id: int, key_prefix: Optional[str] = None) -> str:
        current_sha = get_git_commit_short()
        key = f"{team_id}:{current_sha}:{self.model.__name__}"

        if key_prefix:
            key = f"{key_prefix}:{key}"

        # cache key based on sha to invalidate cache on deploys in case of migrations
        return key

    def get_queryset_repr(self) -> str:
        q, params = self.query.get_compiler(self.db).as_sql()
        return hashlib.sha256(repr((q, params)).encode()).hexdigest()

    def fetch_cached(self, team: "Team", timeout: int = 3600, key_prefix: Optional[str] = None):
        cache_enabled = CACHE_TEST_OVERRIDE if TEST else is_cache_enabled(team)

        if cache_enabled:
            try:
                redis_client = get_client()
                key = self.get_commit_cache_hash_key(team_id=team.pk, key_prefix=key_prefix)
                hash_key = self.get_queryset_repr()

                data = redis_client.hget(key, hash_key)
                if data is not None:
                    DATABASE_CACHE_HIT_COUNTER.labels(model=self.model.__name__).inc()
                    return [deserialized.object for deserialized in serializers.deserialize("json", data)]

                data = serializers.serialize("json", self)

                hash_exists = redis_client.exists(key)

                redis_client.hset(key, hash_key, data)
                if not hash_exists:
                    redis_client.expire(key, timeout)

                DATABASE_CACHE_MISS_COUNTER.labels(model=self.model.__name__).inc()
            except Exception as e:
                capture_exception(e)

        return list(self)

    def invalidate_cache(self, team_id: int, key_prefix: Optional[str] = None):
        try:
            redis_client = get_client()
            key = self.get_commit_cache_hash_key(team_id=team_id, key_prefix=key_prefix)
            deleted_count = redis_client.delete(key)
            if deleted_count > 0:
                DATABASE_INVALIDATION_COUNTER.labels(model=self.model.__name__).inc()
        except Exception as e:
            capture_exception(e)


class CacheManager(Manager.from_queryset(CachedQuerySet)):  # type: ignore
    pass
