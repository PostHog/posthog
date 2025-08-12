"""
Cache management for flag definitions used in local evaluation.

This module provides a centralized way to manage caching of flag definitions,
which includes feature flags, group type mappings, and cohorts.
"""

import logging
import os
from typing import Any, Optional

from django.core.cache import cache
from statshog.defaults.django import statsd


class FlagDefinitionsCache:
    """Manages caching for flag definitions used in local evaluation."""

    # Cache configuration
    CACHE_VERSION = "v1"
    CACHE_DEFAULT_TTL = 3600
    try:
        _cache_ttl_env = os.getenv("FLAG_DEFINITIONS_CACHE_TTL", str(CACHE_DEFAULT_TTL))
        CACHE_TTL = int(_cache_ttl_env)
    except (ValueError, TypeError):
        logger = logging.getLogger(__name__)
        logger.warning(
            f"Invalid FLAG_DEFINITIONS_CACHE_TTL value: '{os.getenv('FLAG_DEFINITIONS_CACHE_TTL')}'. Using default of {CACHE_DEFAULT_TTL} seconds."
        )
        CACHE_TTL = CACHE_DEFAULT_TTL

    @classmethod
    def get_cache_key(cls, project_id: int, include_cohorts: bool = False) -> str:
        """
        Generate cache key for flag definitions.

        Args:
            project_id: The project ID to cache for
            include_cohorts: Whether this cache includes cohort data

        Returns:
            Cache key string
        """
        cohorts_suffix = "cohorts/" if include_cohorts else ""
        return f"local_evaluation/{project_id}/{cohorts_suffix}{cls.CACHE_VERSION}"

    @classmethod
    def get_all_cache_keys(cls, project_id: int) -> list[str]:
        """
        Get both cache keys (with and without cohorts) for a project.

        Args:
            project_id: The project ID

        Returns:
            List of cache keys
        """
        return [
            cls.get_cache_key(project_id, include_cohorts=False),
            cls.get_cache_key(project_id, include_cohorts=True),
        ]

    @classmethod
    def invalidate_for_project(
        cls,
        project_id: int,
        reason: str,
        extra_context: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Invalidate all cache keys for a project with logging.

        Args:
            project_id: The project ID to invalidate cache for
            reason: Human-readable reason for invalidation
            extra_context: Additional context for logging
        """
        try:
            cache_keys = cls.get_all_cache_keys(project_id)
            cache.delete_many(cache_keys)

            # Record cache invalidation metric
            statsd.incr("flag_definitions_cache_invalidation", tags={"reason": reason})

            logger = logging.getLogger(__name__)
            log_extra = {"project_id": project_id, "reason": reason}
            if extra_context:
                log_extra.update(extra_context)

            logger.info(
                f"Invalidated flag definitions cache: {reason}",
                extra=log_extra,
            )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Failed to invalidate flag definitions cache: {reason}",
                extra={
                    "error": str(e),
                    "project_id": project_id,
                    **(extra_context or {}),
                },
            )

    @classmethod
    def set_cache(
        cls,
        project_id: int,
        data: dict[str, Any],
        include_cohorts: bool = False,
    ) -> None:
        """
        Store flag definitions in cache.

        Args:
            project_id: The project ID
            data: Flag definitions data to cache
            include_cohorts: Whether this data includes cohorts
        """
        try:
            cache_key = cls.get_cache_key(project_id, include_cohorts)
            cache.set(cache_key, data, cls.CACHE_TTL)

            # Record cache set metric
            statsd.incr(
                "flag_definitions_cache_set",
                tags={"include_cohorts": str(include_cohorts).lower()},
            )

            logger = logging.getLogger(__name__)
            logger.info(
                "Cached flag definitions for local evaluation",
                extra={"cache_key": cache_key, "project_id": project_id},
            )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(
                "Failed to cache flag definitions",
                extra={"error": str(e), "project_id": project_id},
            )

    @classmethod
    def get_cache(
        cls,
        project_id: int,
        include_cohorts: bool = False,
    ) -> Optional[dict[str, Any]]:
        """
        Retrieve flag definitions from cache.

        Args:
            project_id: The project ID
            include_cohorts: Whether to get cache that includes cohorts

        Returns:
            Cached flag definitions data or None if not found
        """
        try:
            cache_key = cls.get_cache_key(project_id, include_cohorts)
            cached_data = cache.get(cache_key)

            # Record cache hit/miss metrics
            tags = {"include_cohorts": str(include_cohorts).lower()}
            if cached_data is not None:
                statsd.incr("flag_definitions_cache_hit", tags=tags)
                logger = logging.getLogger(__name__)
                logger.info(
                    "Cache hit for local evaluation",
                    extra={"cache_key": cache_key, "project_id": project_id},
                )
            else:
                statsd.incr("flag_definitions_cache_miss", tags=tags)
                logger = logging.getLogger(__name__)
                logger.info(
                    "Cache miss for local evaluation",
                    extra={"cache_key": cache_key, "project_id": project_id},
                )

            return cached_data
        except Exception as e:
            # Record cache error metric
            statsd.incr("flag_definitions_cache_error", tags={"include_cohorts": str(include_cohorts).lower()})
            logger = logging.getLogger(__name__)
            logger.warning(
                "Failed to retrieve flag definitions from cache",
                extra={"error": str(e), "project_id": project_id},
            )
            return None


def invalidate_cache_for_feature_flag_change(feature_flag_instance, activity: str) -> None:
    """Handle cache invalidation for feature flag changes."""
    try:
        project_id = feature_flag_instance.team.project_id
        FlagDefinitionsCache.invalidate_for_project(
            project_id=project_id,
            reason="feature flag change",
            extra_context={
                "flag_key": feature_flag_instance.key,
                "activity": activity,
            },
        )
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(
            "Failed to invalidate flag definitions cache for feature flag change",
            extra={
                "error": str(e),
                "flag_key": getattr(feature_flag_instance, "key", "unknown"),
            },
        )


def invalidate_cache_for_cohort_change(cohort_instance) -> None:
    """Handle cache invalidation for cohort changes."""
    try:
        project_id = cohort_instance.team.project_id
        FlagDefinitionsCache.invalidate_for_project(
            project_id=project_id,
            reason="cohort change",
            extra_context={
                "cohort_id": cohort_instance.pk,
                "cohort_name": cohort_instance.name,
            },
        )
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(
            "Failed to invalidate flag definitions cache for cohort change",
            extra={
                "error": str(e),
                "cohort_id": getattr(cohort_instance, "pk", "unknown"),
            },
        )


def invalidate_cache_for_group_type_mapping_change(group_type_mapping_instance) -> None:
    """Handle cache invalidation for group type mapping changes."""
    try:
        project_id = group_type_mapping_instance.project_id
        FlagDefinitionsCache.invalidate_for_project(
            project_id=project_id,
            reason="group type mapping change",
            extra_context={
                "group_type": group_type_mapping_instance.group_type,
                "group_type_index": group_type_mapping_instance.group_type_index,
            },
        )
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(
            "Failed to invalidate flag definitions cache for group type mapping change",
            extra={
                "error": str(e),
                "group_type": getattr(group_type_mapping_instance, "group_type", "unknown"),
            },
        )
