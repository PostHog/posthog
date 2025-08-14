from datetime import datetime
from typing import Optional

from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager
from posthog.hogql_queries.query_cache_s3 import S3QueryCacheManager


class DualCacheManager(QueryCacheManagerBase):
    """
    Dual cache manager with two modes:

    Mode 1 (s3_enabled=True): Only use S3 cache
    Mode 2 (s3_enabled=False): Write to both Redis and S3, but always read from S3
    """

    def __init__(
        self,
        *,
        team_id: int,
        cache_key: str,
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
        s3_enabled: bool = False,
    ):
        super().__init__(
            team_id=team_id,
            cache_key=cache_key,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )

        self.s3_enabled = s3_enabled

        # Always create S3 cache manager
        self.s3_cache = S3QueryCacheManager(
            team_id=team_id,
            cache_key=cache_key,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )

        # Only create Django cache manager if we're in dual-write mode
        if not s3_enabled:
            self.django_cache = DjangoCacheQueryCacheManager(
                team_id=team_id,
                cache_key=cache_key,
                insight_id=insight_id,
                dashboard_id=dashboard_id,
            )
        else:
            self.django_cache = None

    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        """
        Mode 1 (s3_enabled=True): Write only to S3
        Mode 2 (s3_enabled=False): Write to both Redis and S3
        """
        if self.s3_enabled:
            # Mode 1: Only write to S3
            self.s3_cache.set_cache_data(response=response, target_age=target_age)
        else:
            # Mode 2: Write to both Redis and S3
            # Write to S3 first (primary)
            self.s3_cache.set_cache_data(response=response, target_age=target_age)

            # Also write to Django cache (ignore failures)
            try:
                self.django_cache.set_cache_data(response=response, target_age=target_age)
            except Exception:
                pass

    def get_cache_data(self) -> Optional[dict]:
        """
        Mode 1 (s3_enabled=True): Read only from S3
        Mode 2 (s3_enabled=False): Always read from S3
        """
        # Both modes read from S3
        return self.s3_cache.get_cache_data()
