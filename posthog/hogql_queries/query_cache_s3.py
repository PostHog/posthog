import structlog
from datetime import datetime
from typing import Optional

import zstd
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
    - Stale insights tracking: Redis sorted sets with s3_cache_timestamps prefix

    TTL is implemented using S3 lifecycle rules that automatically expire objects.
    Since S3 lifecycle rules work in days, TTLs are rounded up to the nearest day.

    Uses a different Redis key prefix (s3_cache_timestamps) to avoid conflicts with
    the Django cache query cache implementation.
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
        self.bucket = settings.QUERY_CACHE_S3_BUCKET

    def _cache_object_key(self) -> str:
        """Generate S3 object key for cache data."""
        return f"{settings.OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER}/{self.team_id}/{self.cache_key}"

    @classmethod
    def _redis_key_prefix(cls) -> str:
        """Redis key prefix for S3 cache timestamps to avoid conflicts with Django cache."""
        return "s3_cache_timestamps"

    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        """Store query results in S3 with lifecycle-based TTL."""
        try:
            object_key = self._cache_object_key()
            content = OrjsonJsonSerializer({}).dumps(response)
            payload = zstd.compress(content)

            # Calculate TTL in days for S3 lifecycle rules
            ttl_days = settings.CACHED_RESULTS_TTL_DAYS

            # Add S3 object tags for lifecycle management
            extras = {"Tagging": f"ttl_days={ttl_days}&cache_type=query_data&team_id={self.team_id}"}

            self.storage_client.write(bucket=self.bucket, key=object_key, content=payload, extras=extras)

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
            capture_exception(e)
            raise ObjectStorageError("Failed to set cache data") from e

    def get_cache_data(self) -> Optional[dict]:
        """Retrieve query results from S3."""
        try:
            object_key = self._cache_object_key()
            payload = self.storage_client.read_bytes(bucket=self.bucket, key=object_key)

            if not payload:
                logger.debug(
                    "s3_query_cache.get_miss",
                    team_id=self.team_id,
                    cache_key=self.cache_key,
                    object_key=object_key,
                )
                return None

            try:
                decompressed = zstd.decompress(payload)
            except zstd.ZstdError as decomp_error:
                logger.warning(
                    "s3_query_cache.decompression_failed",
                    team_id=self.team_id,
                    cache_key=self.cache_key,
                    object_key=object_key,
                    error=str(decomp_error),
                )
                capture_exception(decomp_error)
                return None

            try:
                result = OrjsonJsonSerializer({}).loads(decompressed)
            except (ValueError, TypeError) as json_error:
                logger.warning(
                    "s3_query_cache.json_parsing_failed",
                    team_id=self.team_id,
                    cache_key=self.cache_key,
                    object_key=object_key,
                    error=str(json_error),
                )
                capture_exception(json_error)
                return None

            logger.debug(
                "s3_query_cache.get_hit",
                team_id=self.team_id,
                cache_key=self.cache_key,
                object_key=object_key,
            )
            return result

        except Exception as e:
            capture_exception(e)
            return None
