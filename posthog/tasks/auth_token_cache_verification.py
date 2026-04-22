"""
Celery task for periodic auth token cache verification.

Scans all per-token auth cache entries in Redis and verifies them against
the database, deleting any stale entries that signal-based invalidation
may have missed. This is a safety net for long-TTL cache entries.
"""

import time

from django.conf import settings
from django.core.cache import cache as django_cache

import structlog
from celery import shared_task

from posthog.exceptions_capture import capture_exception
from posthog.tasks.utils import CeleryQueue, PushGatewayTask

logger = structlog.get_logger(__name__)

# Lock timeout is aligned with the Celery hard time_limit to prevent overlapping runs.
# The Redis lock TTL must be >= the task's hard time_limit so that, in the worst case
# where the worker is SIGKILLed at time_limit and our `finally` block cannot run, the
# lock still remains held for as long as the task could be executing.
# If LOCK_TIMEOUT_SECONDS were < time_limit, the lock could expire while the task is
# still running, allowing another scheduled run to acquire the lock and overlap work.
# The soft_time_limit (20 min) raises SoftTimeLimitExceeded, which is caught by the
# outer `except`, and the `finally` block then releases the lock explicitly.
# With a 6-hour schedule and a 25-minute lock TTL >= time_limit, a killed task's lock
# expires well before the next scheduled invocation but not before the first run has
# definitely stopped.
LOCK_KEY = "posthog:auth_token_verification:lock"
LOCK_TIMEOUT_SECONDS = 25 * 60  # 25 minutes — must be >= time_limit (see above)


@shared_task(
    bind=True,
    base=PushGatewayTask,
    ignore_result=True,
    queue=CeleryQueue.FEATURE_FLAGS_LONG_RUNNING.value,
    soft_time_limit=20 * 60,  # 20 min soft limit
    time_limit=25 * 60,  # 25 min hard limit (matches LOCK_TIMEOUT_SECONDS)
)
def verify_and_fix_auth_token_cache_task(self: PushGatewayTask) -> None:
    """Periodic task to verify auth token cache entries against the database.

    Runs every 6 hours. Scans all posthog:auth_token:* keys in Redis,
    deserializes the cached TokenAuthData, and deletes entries that no longer
    match the database (deleted tokens, deactivated users, changed scopes, etc.).

    Uses a distributed lock to skip execution if a previous run is still in progress.

    Metrics: posthog_tombstone_total{namespace="auth_token", component="auth_token_cache_verifier"}
    """
    if not settings.FLAGS_REDIS_URL:
        logger.info("FLAGS_REDIS_URL not set, skipping auth token cache verification")
        return

    if not django_cache.add(LOCK_KEY, "locked", timeout=LOCK_TIMEOUT_SECONDS):
        logger.info("Skipping auth token cache verification - already running")
        return

    try:
        from posthog.redis import get_client
        from posthog.storage.auth_token_cache_verifier import verify_and_fix_auth_token_cache

        redis_client = get_client(settings.FLAGS_REDIS_URL)
        start_time = time.time()

        result = verify_and_fix_auth_token_cache(redis_client)

        duration = time.time() - start_time
        logger.info(
            "Completed auth token cache verification",
            total_scanned=result.total_scanned,
            valid=result.valid,
            stale_found=result.stale_found,
            stale_by_type=result.stale_by_type,
            parse_errors=result.parse_errors,
            db_errors=result.db_errors,
            delete_errors=result.delete_errors,
            duration_seconds=duration,
        )
    except Exception as e:
        logger.exception("Failed auth token cache verification")
        capture_exception(e)
        raise
    finally:
        django_cache.delete(LOCK_KEY)
