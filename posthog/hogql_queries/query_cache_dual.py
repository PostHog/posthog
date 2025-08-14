import structlog
from datetime import datetime
from typing import Optional

from posthog.hogql_queries.query_cache_base import QueryCacheManagerBase
from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager
from posthog.hogql_queries.query_cache_s3 import S3QueryCacheManager
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)


class DualQueryCacheManager(QueryCacheManagerBase):
    """
    Dual-write query cache manager that writes to both S3 and Redis but reads from one.

    This manager allows for safe migration between cache backends by:
    - Writing to both S3 and Redis/Django cache simultaneously
    - Reading from the cache specified by the feature flag
    - Falling back gracefully if one cache fails
    """

    def __init__(
        self,
        *,
        team_id: int,
        cache_key: str,
        insight_id: Optional[int] = None,
        dashboard_id: Optional[int] = None,
        prefer_s3: bool = False,
    ):
        super().__init__(
            team_id=team_id,
            cache_key=cache_key,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )

        self.prefer_s3 = prefer_s3

        # Initialize both cache managers
        self.s3_cache = S3QueryCacheManager(
            team_id=team_id,
            cache_key=cache_key,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )

        self.django_cache = DjangoCacheQueryCacheManager(
            team_id=team_id,
            cache_key=cache_key,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
        )

    def set_cache_data(self, *, response: dict, target_age: Optional[datetime]) -> None:
        """Write to both S3 and Redis/Django cache."""
        s3_success = False
        django_success = False

        # Try to write to S3
        try:
            self.s3_cache.set_cache_data(response=response, target_age=target_age)
            s3_success = True
            logger.debug(
                "dual_query_cache.s3_write_success",
                team_id=self.team_id,
                cache_key=self.cache_key,
            )
        except Exception as e:
            logger.warning(
                "dual_query_cache.s3_write_failed",
                team_id=self.team_id,
                cache_key=self.cache_key,
                error=str(e),
            )
            capture_exception(e)

        # Try to write to Django cache
        try:
            self.django_cache.set_cache_data(response=response, target_age=target_age)
            django_success = True
            logger.debug(
                "dual_query_cache.django_write_success",
                team_id=self.team_id,
                cache_key=self.cache_key,
            )
        except Exception as e:
            logger.warning(
                "dual_query_cache.django_write_failed",
                team_id=self.team_id,
                cache_key=self.cache_key,
                error=str(e),
            )
            capture_exception(e)

        # Log the overall write status
        if s3_success and django_success:
            logger.debug(
                "dual_query_cache.dual_write_success",
                team_id=self.team_id,
                cache_key=self.cache_key,
            )
        elif s3_success or django_success:
            logger.warning(
                "dual_query_cache.partial_write_success",
                team_id=self.team_id,
                cache_key=self.cache_key,
                s3_success=s3_success,
                django_success=django_success,
            )
        else:
            logger.error(
                "dual_query_cache.dual_write_failed",
                team_id=self.team_id,
                cache_key=self.cache_key,
            )
            raise Exception("Failed to write to both S3 and Django cache")

    def get_cache_data(self) -> Optional[dict]:
        """Read from the preferred cache based on feature flag, with fallback."""
        if self.prefer_s3:
            # Try S3 first, fallback to Django cache
            try:
                result = self.s3_cache.get_cache_data()
                if result is not None:
                    logger.debug(
                        "dual_query_cache.s3_read_success",
                        team_id=self.team_id,
                        cache_key=self.cache_key,
                    )
                    return result
                else:
                    logger.debug(
                        "dual_query_cache.s3_read_miss",
                        team_id=self.team_id,
                        cache_key=self.cache_key,
                    )
            except Exception as e:
                logger.warning(
                    "dual_query_cache.s3_read_failed",
                    team_id=self.team_id,
                    cache_key=self.cache_key,
                    error=str(e),
                )
                capture_exception(e)

            # Fallback to Django cache
            try:
                result = self.django_cache.get_cache_data()
                if result is not None:
                    logger.debug(
                        "dual_query_cache.fallback_django_read_success",
                        team_id=self.team_id,
                        cache_key=self.cache_key,
                    )
                return result
            except Exception as e:
                logger.warning(
                    "dual_query_cache.fallback_django_read_failed",
                    team_id=self.team_id,
                    cache_key=self.cache_key,
                    error=str(e),
                )
                capture_exception(e)
                return None
        else:
            # Try Django cache first, fallback to S3
            try:
                result = self.django_cache.get_cache_data()
                if result is not None:
                    logger.debug(
                        "dual_query_cache.django_read_success",
                        team_id=self.team_id,
                        cache_key=self.cache_key,
                    )
                    return result
                else:
                    logger.debug(
                        "dual_query_cache.django_read_miss",
                        team_id=self.team_id,
                        cache_key=self.cache_key,
                    )
            except Exception as e:
                logger.warning(
                    "dual_query_cache.django_read_failed",
                    team_id=self.team_id,
                    cache_key=self.cache_key,
                    error=str(e),
                )
                capture_exception(e)

            # Fallback to S3
            try:
                result = self.s3_cache.get_cache_data()
                if result is not None:
                    logger.debug(
                        "dual_query_cache.fallback_s3_read_success",
                        team_id=self.team_id,
                        cache_key=self.cache_key,
                    )
                return result
            except Exception as e:
                logger.warning(
                    "dual_query_cache.fallback_s3_read_failed",
                    team_id=self.team_id,
                    cache_key=self.cache_key,
                    error=str(e),
                )
                capture_exception(e)
                return None
