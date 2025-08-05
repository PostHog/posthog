import math
import structlog
from datetime import datetime
from typing import Optional

from django.conf import settings

from posthog.cache_utils import OrjsonJsonSerializer
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.storage.object_storage import object_storage_client, ObjectStorageError

logger = structlog.get_logger(__name__)


class S3QueryCacheManager(QueryCacheManagerBase):
    """
    Hybrid query cache manager using S3 for data storage and Redis for tracking.

    Cache structure:
    - Cache data: S3 'query_cache/{team_id}/{cache_key}' -> query_results (JSON)
    - Stale insights tracking: Redis sorted sets (inherited from base class)

    TTL is implemented using S3 lifecycle rules that automatically expire objects.
    Since S3 lifecycle rules work in days, TTLs are rounded up to the nearest day.
    """

    def __init__(
        self,
        *,
        team_id: int,
        cache_key: str,
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
    ):
        super().__init__(
            team_id=team_id,
            cache_key=cache_key,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )
        self.storage_client = object_storage_client()
        self.bucket = settings.QUERY_CACHE_S3_BUCKET or settings.OBJECT_STORAGE_BUCKET

    def _cache_object_key(self) -> str:
        """Generate S3 object key for cache data."""
        return f"query_cache/{self.team_id}/{self.cache_key}"

    def _calculate_ttl_days(self, ttl_seconds: int) -> int:
        """
        Calculate TTL in days for S3 lifecycle rules.
        S3 lifecycle rules work in days, so we round up to ensure data isn't expired too early.
        """
        return max(1, math.ceil(ttl_seconds / 86400))  # 86400 seconds = 1 day

    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        """Store query results in S3 with lifecycle-based TTL."""
        try:
            object_key = self._cache_object_key()
            content = OrjsonJsonSerializer({}).dumps(response).decode("utf-8")

            # Calculate TTL in days for S3 lifecycle rules
            ttl_seconds = getattr(settings, "CACHED_RESULTS_TTL", 86400)  # Default 1 day
            ttl_days = self._calculate_ttl_days(ttl_seconds)

            # Add S3 object tags for lifecycle management
            extras = {"Tagging": f"ttl_days={ttl_days}&cache_type=query_data&team_id={self.team_id}"}

            self.storage_client.write(bucket=self.bucket, key=object_key, content=content, extras=extras)

            logger.debug(
                "s3_query_cache.set_success",
                team_id=self.team_id,
                cache_key=self.cache_key,
                object_key=object_key,
                ttl_days=ttl_days,
            )

            # Update target age tracking if provided (uses Redis from base class)
            if target_age:
                self.update_target_age(target_age)
            else:
                self.remove_last_refresh()

        except Exception as e:
            logger.exception("s3_query_cache.set_failed", team_id=self.team_id, cache_key=self.cache_key, error=str(e))
            capture_exception(e)
            raise ObjectStorageError("Failed to set cache data") from e

    def get_cache_data(self) -> Optional[dict]:
        """Retrieve query results from S3."""
        try:
            object_key = self._cache_object_key()
            content = self.storage_client.read(bucket=self.bucket, key=object_key)

            if not content:
                logger.debug(
                    "s3_query_cache.get_miss",
                    team_id=self.team_id,
                    cache_key=self.cache_key,
                    object_key=object_key,
                )
                return None

            result = OrjsonJsonSerializer({}).loads(content.encode("utf-8"))
            logger.debug(
                "s3_query_cache.get_hit",
                team_id=self.team_id,
                cache_key=self.cache_key,
                object_key=object_key,
            )
            return result

        except Exception as e:
            logger.warning(
                "s3_query_cache.get_failed",
                team_id=self.team_id,
                cache_key=self.cache_key,
                error=str(e),
            )
            capture_exception(e)
            return None
