import structlog
from datetime import datetime
from typing import Optional

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager
from posthog.hogql_queries.query_cache_s3 import S3QueryCacheManager

logger = structlog.get_logger(__name__)


class DualCacheManager(DjangoCacheQueryCacheManager):
    """
    Dual cache manager that extends DjangoCacheQueryCacheManager.

    Inherits all behavior from DjangoCacheQueryCacheManager (Redis/Django cache)
    but also writes to S3 when setting cache data.

    This allows for migration from Redis to S3 by populating S3 while
    maintaining all existing Redis-based behavior.
    """

    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        """Write to both Redis (via parent) and S3."""
        # Call parent method to write to Redis/Django cache
        super().set_cache_data(response=response, target_age=target_age)

        # Also write to S3 for migration purposes
        try:
            s3_cache = S3QueryCacheManager(
                team_id=self.team_id,
                cache_key=self.cache_key,
                insight_id=self.insight_id,
                dashboard_id=self.dashboard_id,
            )
            s3_cache.set_cache_data(response=response, target_age=target_age)
        except Exception as e:
            capture_exception(e)
            # Don't re-raise - S3 write failure shouldn't break Redis functionality
