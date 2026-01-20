"""
Celery tasks for HyperCache verification.

Provides separate tasks for verifying and fixing each HyperCache-backed cache
(flags, team metadata). Split into separate tasks to:
- Give each cache its own time budget (avoiding timeouts)
- Enable independent monitoring and metrics
- Allow parallel execution when workers are available
- Isolate failures so one cache's issues don't affect the other
"""

import time
from collections.abc import Callable
from typing import Literal

from django.conf import settings
from django.core.cache import cache as django_cache

import structlog
from celery import shared_task

from posthog.exceptions_capture import capture_exception
from posthog.models.feature_flag.local_evaluation import (
    FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG,
    FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG,
    verify_team_flag_definitions,
)
from posthog.models.team.team import Team
from posthog.storage.hypercache_verifier import _run_verification_for_cache
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

CacheType = Literal["flags", "team_metadata"]

# Lock timeout matches time_limit to ensure lock is released if task is killed.
# Reduced from 1 hour to 25 minutes to enable faster recovery when tasks crash
# (OOM, deploy kills) without executing their finally block. With 30-minute
# scheduling and 25-minute lock timeout, a crashed task's lock expires before
# the next scheduled run, so at most 1 run is skipped after a crash.
LOCK_TIMEOUT_SECONDS = 25 * 60  # 25 minutes

# Flag definitions verification has a longer time limit (4 hours) because it verifies
# two cache variants (with-cohorts and without-cohorts) for all teams. The lock timeout
# must match the task's time_limit to prevent concurrent executions.
FLAG_DEFINITIONS_LOCK_TIMEOUT_SECONDS = 4 * 60 * 60  # 4 hours


def _run_flag_definitions_verification() -> None:
    """
    Run verification for both flag definitions cache variants.

    Handles:
    - Early exit if FLAGS_REDIS_URL not configured
    - Distributed lock to prevent concurrent executions
    - Verifying both with-cohorts and without-cohorts variants
    """
    cache_type = "flag_definitions"

    # Check Redis URL first to avoid holding a lock when no work will be done
    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping cache verification", cache_type=cache_type)
        return

    lock_key = f"posthog:hypercache_verification:{cache_type}:lock"

    # Attempt to acquire lock - cache.add returns False if key already exists
    # Use dedicated timeout that matches the task's 4-hour time limit
    if not django_cache.add(lock_key, "locked", timeout=FLAG_DEFINITIONS_LOCK_TIMEOUT_SECONDS):
        logger.info("Skipping cache verification - already running", cache_type=cache_type)
        return

    try:
        logger.info("Starting cache verification", cache_type=cache_type)

        start_time = time.time()

        # Verify both cache variants
        configs = [
            (FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG, "with_cohorts", True),
            (FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG, "without_cohorts", False),
        ]

        for config, variant_name, include_cohorts in configs:
            try:
                # Create a variant-specific verify function
                def make_verify_fn(
                    inc_cohorts: bool,
                ) -> Callable[[Team, dict | None, dict | None], dict]:
                    def verify_fn(
                        team: Team,
                        db_batch_data: dict | None = None,
                        cache_batch_data: dict | None = None,
                        verbose: bool = False,
                    ) -> dict:
                        return verify_team_flag_definitions(
                            team,
                            db_batch_data=db_batch_data,
                            cache_batch_data=cache_batch_data,
                            include_cohorts=inc_cohorts,
                            verbose=verbose,
                        )

                    return verify_fn

                _run_verification_for_cache(
                    config=config,
                    verify_team_fn=make_verify_fn(include_cohorts),
                    cache_type=f"{cache_type}_{variant_name}",
                    chunk_size=settings.FLAGS_CACHE_VERIFICATION_CHUNK_SIZE,
                )
            except Exception as e:
                logger.exception(
                    "Failed cache verification for variant",
                    cache_type=cache_type,
                    variant=variant_name,
                    error=str(e),
                )
                capture_exception(e)
                # Continue to next variant

        duration = time.time() - start_time
        logger.info("Completed cache verification", cache_type=cache_type, duration_seconds=duration)
    finally:
        django_cache.delete(lock_key)


def _run_cache_verification(cache_type: CacheType, chunk_size: int) -> None:
    """
    Run verification for a specific cache type.

    Shared logic for all HyperCache verification tasks. Handles:
    - Early exit if FLAGS_REDIS_URL not configured
    - Distributed lock to prevent concurrent executions
    - Importing cache-specific config and verify function
    - Running verification with timing and error handling
    """
    # Check Redis URL first to avoid holding a lock when no work will be done
    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping cache verification", cache_type=cache_type)
        return

    lock_key = f"posthog:hypercache_verification:{cache_type}:lock"

    # Attempt to acquire lock - cache.add returns False if key already exists
    if not django_cache.add(lock_key, "locked", timeout=LOCK_TIMEOUT_SECONDS):
        logger.info("Skipping cache verification - already running", cache_type=cache_type)
        return

    try:
        logger.info("Starting cache verification", cache_type=cache_type, chunk_size=chunk_size)

        # Import cache-specific config and verify function
        if cache_type == "flags":
            from posthog.models.feature_flag.flags_cache import (
                FLAGS_HYPERCACHE_MANAGEMENT_CONFIG as config,
                verify_team_flags as verify_fn,
            )
        else:
            from posthog.storage.team_metadata_cache import (
                TEAM_HYPERCACHE_MANAGEMENT_CONFIG as config,
                verify_team_metadata as verify_fn,
            )

        start_time = time.time()

        try:
            _run_verification_for_cache(
                config=config, verify_team_fn=verify_fn, cache_type=cache_type, chunk_size=chunk_size
            )
        except Exception as e:
            logger.exception("Failed cache verification", cache_type=cache_type, error=str(e))
            capture_exception(e)
            raise

        duration = time.time() - start_time
        logger.info("Completed cache verification", cache_type=cache_type, duration_seconds=duration)
    finally:
        django_cache.delete(lock_key)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    soft_time_limit=20 * 60,  # 20 min soft limit
    time_limit=25 * 60,  # 25 min hard limit (matches LOCK_TIMEOUT_SECONDS)
)
def verify_and_fix_flags_cache_task() -> None:
    """
    Periodic task to verify the flags HyperCache and fix issues.

    Runs every 30 minutes. Verifies all teams' flags caches, automatically
    fixing any cache misses, mismatches, or expiry tracking issues.
    Uses a distributed lock to skip execution if a previous run is still in progress.

    Expected duration: ~8-10 minutes with 250-team batch size.

    Metrics: posthog_hypercache_verify_fixes_total{cache_type="flags", issue_type="..."}
    """
    _run_cache_verification("flags", settings.FLAGS_CACHE_VERIFICATION_CHUNK_SIZE)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    soft_time_limit=20 * 60,  # 20 min soft limit
    time_limit=25 * 60,  # 25 min hard limit (matches LOCK_TIMEOUT_SECONDS)
)
def verify_and_fix_team_metadata_cache_task() -> None:
    """
    Periodic task to verify the team metadata HyperCache and fix issues.

    Runs hourly at minute 20. Verifies all teams' metadata caches,
    automatically fixing any cache misses, mismatches, or expiry tracking issues.
    Uses a distributed lock to skip execution if a previous run is still in progress.

    Expected duration: ~3-5 minutes with 1000-team batch size.

    Metrics: posthog_hypercache_verify_fixes_total{cache_type="team_metadata", issue_type="..."}
    """
    _run_cache_verification("team_metadata", settings.TEAM_METADATA_CACHE_VERIFICATION_CHUNK_SIZE)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    soft_time_limit=3 * 60 * 60 + 30 * 60,  # 3h 30min soft limit
    time_limit=4 * 60 * 60,  # 4 hour hard limit (distributed lock prevents overlap)
)
def verify_and_fix_flag_definitions_cache_task() -> None:
    """
    Periodic task to verify the flag definitions HyperCaches and fix issues.

    Runs hourly at minute 50. Verifies all teams' flag definitions caches
    (both with-cohorts and without-cohorts variants), automatically fixing any
    cache misses, mismatches, or expiry tracking issues.

    Uses a distributed lock to skip execution if a previous run is still in progress.

    Metrics: posthog_hypercache_verify_fixes_total{cache_type="flag_definitions", issue_type="..."}
    """
    _run_flag_definitions_verification()
