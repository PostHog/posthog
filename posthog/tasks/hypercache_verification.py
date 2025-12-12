"""
Celery task for HyperCache verification.

Provides a unified task for verifying and fixing all HyperCache-backed caches
(flags, team metadata, etc.) in a single scheduled job.
"""

import time

from django.conf import settings

import structlog
from celery import shared_task

from posthog.exceptions_capture import capture_exception
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    soft_time_limit=3600,  # 60 min warning (verifying both caches)
    time_limit=4200,  # 70 min hard limit
)
def verify_and_fix_hypercaches_task() -> None:
    """
    Periodic task to verify all HyperCache-backed caches and fix issues.

    Runs hourly at minute 30. Verifies all teams for both team_metadata and flags
    caches, automatically fixing any cache misses, mismatches, or expiry tracking issues.

    Metrics: posthog_hypercache_verify_fixes_total{cache_type="...", issue_type="..."}
    """
    if not settings.FLAGS_REDIS_URL:
        logger.info("Flags Redis URL not set, skipping HyperCache verification")
        return

    # Import here to avoid circular imports
    from posthog.models.feature_flag.flags_cache import FLAGS_HYPERCACHE_MANAGEMENT_CONFIG, verify_team_flags
    from posthog.storage.hypercache_verifier import _run_verification_for_cache
    from posthog.storage.team_metadata_cache import TEAM_HYPERCACHE_MANAGEMENT_CONFIG, verify_team_metadata

    start_time = time.time()
    logger.info("Starting HyperCache verification for all caches")

    errors: list[Exception] = []

    # Verify team metadata cache
    try:
        _run_verification_for_cache(
            config=TEAM_HYPERCACHE_MANAGEMENT_CONFIG,
            verify_team_fn=verify_team_metadata,
            cache_type="team_metadata",
        )
    except Exception as e:
        logger.exception("Failed team_metadata cache verification", error=str(e))
        capture_exception(e)
        errors.append(e)

    # Verify flags cache
    try:
        _run_verification_for_cache(
            config=FLAGS_HYPERCACHE_MANAGEMENT_CONFIG,
            verify_team_fn=verify_team_flags,
            cache_type="flags",
        )
    except Exception as e:
        logger.exception("Failed flags cache verification", error=str(e))
        capture_exception(e)
        errors.append(e)

    duration = time.time() - start_time
    logger.info(
        "Completed HyperCache verification for all caches",
        duration_seconds=duration,
        errors_count=len(errors),
    )

    # Re-raise first error if any occurred
    if errors:
        raise errors[0]
