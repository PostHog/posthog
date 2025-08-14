from typing import Optional
from django.core import serializers
from django.db.models import QuerySet, Manager
from posthog.exceptions_capture import capture_exception
from posthog.git import get_git_commit_short
from posthog.redis import get_client
from posthog.settings import TEST


class CachedQuerySet(QuerySet):
    def get_commit_cache_key(self, team_id: int, key_prefix: Optional[str] = None) -> str:
        current_sha = get_git_commit_short()
        key = f"{team_id}:{current_sha}:{self.model.__name__}"

        if key_prefix:
            key = f"{key_prefix}:{key}"

        # cache key based on sha to invalidate cache on deploys in case of migrations
        return key

    def fetch_cached(self, team_id: int, timeout: int = 300, key_prefix: Optional[str] = None):
        if TEST:
            return list(self)

        try:
            redis_client = get_client()
            key = self.get_commit_cache_key(team_id=team_id, key_prefix=key_prefix)

            data = redis_client.get(key)
            if data is not None:
                return [deserialized.object for deserialized in serializers.deserialize("json", data)]

            data = serializers.serialize("json", self)

            redis_client.set(key, data, ex=timeout)

        except Exception as e:
            capture_exception(e)

        return list(self)

    def invalidate_cache(self, team_id: int, key_prefix: Optional[str] = None):
        try:
            redis_client = get_client()
            key = self.get_commit_cache_key(team_id=team_id, key_prefix=key_prefix)
            redis_client.delete(key)
        except Exception as e:
            capture_exception(e)


class CacheManager(Manager.from_queryset(CachedQuerySet)):  # type: ignore
    pass
