import math
import structlog
from datetime import datetime, UTC
from typing import Optional

from django.conf import settings

from posthog.cache_utils import OrjsonJsonSerializer
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.storage.object_storage import object_storage_client, ObjectStorageError

logger = structlog.get_logger(__name__)


class S3QueryCacheManager(QueryCacheManagerBase):
    """
    Storing query results in S3 with lifecycle-based TTL management.

    Cache structure:
    - Cache data: 'query_cache/{team_id}/{cache_key}' -> query_results (JSON)
    - Stale insights tracking: 'query_cache_timestamps/{team_id}/{insight_id}_{dashboard_id}' -> target_age metadata

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

    def _stale_insights_object_key(self) -> str:
        """Generate S3 object key for stale insights tracking."""
        return f"query_cache_timestamps/{self.team_id}/{self.identifier}"

    def _get_ttl_days(self, ttl_seconds: Optional[int] = None) -> int:
        """
        Convert TTL seconds to days, rounding up.
        S3 lifecycle rules work in days, so we need to round up to ensure data is retained
        for at least the required duration.
        """
        if ttl_seconds is None:
            ttl_seconds = getattr(settings, "CACHED_RESULTS_TTL", 86400)  # 1 day default

        return max(1, math.ceil(ttl_seconds / 86400))  # Round up to nearest day, minimum 1 day

    def get_cache_data(self) -> Optional[dict]:
        """Retrieve cached query results from S3."""
        try:
            object_key = self._cache_object_key()
            cached_response_str = self.storage_client.read(self.bucket, object_key)

            if not cached_response_str:
                return None

            return OrjsonJsonSerializer({}).loads(cached_response_str.encode("utf-8"))

        except Exception as e:
            logger.warning("s3_query_cache.get_failed", team_id=self.team_id, cache_key=self.cache_key, error=str(e))
            capture_exception(e)
            return None

    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        """Store query results in S3 with lifecycle-based TTL."""
        try:
            # Serialize and store the response
            fresh_response_serialized = OrjsonJsonSerializer({}).dumps(response)
            object_key = self._cache_object_key()

            # Calculate TTL in days for lifecycle rule
            ttl_days = self._get_ttl_days()

            # Use object tags to set TTL via lifecycle rules
            # The lifecycle rule should be configured to delete objects with tag "ttl_days" after that many days
            extras = {"Tagging": f"ttl_days={ttl_days}&cache_type=query_results"}

            self.storage_client.write(
                bucket=self.bucket, key=object_key, content=fresh_response_serialized.decode("utf-8"), extras=extras
            )

            logger.debug(
                "s3_query_cache.set_success", team_id=self.team_id, cache_key=self.cache_key, ttl_days=ttl_days
            )

            # Update target age tracking if provided
            if target_age:
                self.update_target_age(target_age)
            else:
                self.remove_last_refresh()

        except Exception as e:
            logger.exception("s3_query_cache.set_failed", team_id=self.team_id, cache_key=self.cache_key, error=str(e))
            capture_exception(e)
            raise ObjectStorageError("Failed to set cache data") from e

    def update_target_age(self, target_age: datetime) -> None:
        """Store target age for insight freshness tracking."""
        if not self.insight_id:
            return

        try:
            object_key = self._stale_insights_object_key()

            # Store target age as JSON with metadata
            target_age_data = {
                "target_age": target_age.isoformat(),
                "insight_id": self.insight_id,
                "dashboard_id": self.dashboard_id,
                "team_id": self.team_id,
                "updated_at": datetime.now(UTC).isoformat(),
            }

            content = OrjsonJsonSerializer({}).dumps(target_age_data).decode("utf-8")

            # Use a longer TTL for tracking objects (30 days)
            extras = {"Tagging": "ttl_days=30&cache_type=target_age"}

            self.storage_client.write(bucket=self.bucket, key=object_key, content=content, extras=extras)

        except Exception as e:
            logger.warning(
                "s3_query_cache.update_target_age_failed",
                team_id=self.team_id,
                insight_id=self.insight_id,
                error=str(e),
            )
            capture_exception(e)

    def remove_last_refresh(self) -> None:
        """Remove insight from freshness tracking."""
        if not self.insight_id:
            return

        try:
            object_key = self._stale_insights_object_key()
            self.storage_client.delete(self.bucket, object_key)

        except Exception as e:
            logger.warning(
                "s3_query_cache.remove_last_refresh_failed",
                team_id=self.team_id,
                insight_id=self.insight_id,
                error=str(e),
            )
            capture_exception(e)

    @staticmethod
    def get_stale_insights(*, team_id: int, limit: Optional[int] = None) -> list[str]:
        """
        Get list of stale insights by scanning S3 objects.

        This is less efficient than Redis sorted sets, but works by:
        1. Listing all target_age tracking objects for the team
        2. Checking if their target_age is in the past
        3. Returning the stale ones in order of staleness
        """
        try:
            storage_client = object_storage_client()
            bucket = settings.QUERY_CACHE_S3_BUCKET or settings.OBJECT_STORAGE_BUCKET
            prefix = f"query_cache_timestamps/{team_id}/"

            # List all target age tracking objects for this team
            object_keys = storage_client.list_objects(bucket, prefix) or []

            stale_insights = []
            current_time = datetime.now(UTC)

            for object_key in object_keys:
                try:
                    # Read target age data
                    content = storage_client.read(bucket, object_key)
                    if not content:
                        continue

                    target_age_data = OrjsonJsonSerializer({}).loads(content.encode("utf-8"))
                    target_age_str = target_age_data.get("target_age")

                    if target_age_str:
                        target_age = datetime.fromisoformat(target_age_str.replace("Z", "+00:00"))

                        # Check if target age is in the past (stale)
                        if target_age < current_time:
                            # Extract identifier from object key
                            identifier = object_key.split("/")[-1]  # Get last part after final /
                            stale_insights.append((identifier, target_age))

                except Exception as e:
                    logger.warning(
                        "s3_query_cache.get_stale_insights_parse_failed",
                        team_id=team_id,
                        object_key=object_key,
                        error=str(e),
                    )
                    continue

            # Sort by target age (most stale first), then apply limit
            stale_insights.sort(key=lambda x: x[1])
            result = [identifier for identifier, _ in stale_insights]

            if limit:
                result = result[:limit]

            return result

        except Exception as e:
            logger.exception("s3_query_cache.get_stale_insights_failed", team_id=team_id, error=str(e))
            capture_exception(e)
            return []

    @staticmethod
    def clean_up_stale_insights(*, team_id: int, threshold: datetime) -> None:
        """
        Remove stale insights older than threshold.

        Since S3 lifecycle rules handle TTL, this mainly cleans up target_age tracking objects
        that are older than the threshold.
        """
        try:
            storage_client = object_storage_client()
            bucket = settings.QUERY_CACHE_S3_BUCKET or settings.OBJECT_STORAGE_BUCKET
            prefix = f"query_cache_timestamps/{team_id}/"

            # List all target age tracking objects for this team
            object_keys = storage_client.list_objects(bucket, prefix) or []

            for object_key in object_keys:
                try:
                    # Read target age data
                    content = storage_client.read(bucket, object_key)
                    if not content:
                        continue

                    target_age_data = OrjsonJsonSerializer({}).loads(content.encode("utf-8"))
                    target_age_str = target_age_data.get("target_age")

                    if target_age_str:
                        target_age = datetime.fromisoformat(target_age_str.replace("Z", "+00:00"))

                        # Delete if older than threshold
                        if target_age < threshold:
                            storage_client.delete(bucket, object_key)
                            logger.debug(
                                "s3_query_cache.cleaned_up_stale_insight",
                                team_id=team_id,
                                object_key=object_key,
                                target_age=target_age_str,
                            )

                except Exception as e:
                    logger.warning(
                        "s3_query_cache.clean_up_stale_insights_item_failed",
                        team_id=team_id,
                        object_key=object_key,
                        error=str(e),
                    )
                    continue

        except Exception as e:
            logger.exception(
                "s3_query_cache.clean_up_stale_insights_failed",
                team_id=team_id,
                threshold=threshold.isoformat(),
                error=str(e),
            )
            capture_exception(e)
