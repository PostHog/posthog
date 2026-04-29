"""
Targeted invalidation for the per-token auth cache.

Sync functions are called by Django signal handlers to invalidate cache
entries immediately. Each has an async Celery task counterpart used as
a retry fallback if the synchronous attempt fails.
"""

from collections.abc import Callable
from typing import Any

import structlog
from celery import Task, shared_task
from prometheus_client import Counter

from posthog.exceptions_capture import capture_exception
from posthog.storage.team_access_cache import token_auth_cache

logger = structlog.get_logger(__name__)

AUTH_TOKEN_INVALIDATION_FAILURE_COUNTER = Counter(
    "posthog_auth_token_invalidation_failures_total",
    "Auth token cache invalidation failures after all retries exhausted",
    labelnames=["invalidation_type"],
)


# --- Sync-with-async-fallback helper ---


def _sync_with_async_fallback(
    action: Callable[[], None],
    fallback_task: Task,
    fallback_args: list[Any],
    result_context: dict,
) -> dict:
    """Run a cache invalidation synchronously, falling back to an async Celery retry on failure.

    All token invalidation is security-sensitive: a revoked token must stop
    working immediately, not after Celery queue delay. If the sync attempt
    fails (e.g., brief Redis blip), we schedule an async retry as a safety net.
    """
    try:
        action()
        return {"status": "success", **result_context}
    except Exception as e:
        capture_exception(e)
        logger.exception("Sync invalidation failed, scheduling async retry", **result_context)
        try:
            fallback_task.apply_async(args=fallback_args, countdown=5)
        except Exception as retry_exc:
            capture_exception(retry_exc)
            AUTH_TOKEN_INVALIDATION_FAILURE_COUNTER.labels(invalidation_type="schedule_fallback").inc()
            logger.exception("Failed to schedule async retry", **result_context)
        return {"status": "failure", **result_context}


# --- Celery tasks (used as async retry fallback) ---


@shared_task(bind=True, max_retries=3, ignore_result=True)
def invalidate_token_cache_task(self: Task, token_hash: str) -> dict:
    """Invalidate a single token's cache entry.

    Used as the async retry fallback for invalidate_token_sync.
    """
    try:
        token_auth_cache.invalidate_token(token_hash)
        return {"status": "success", "token_prefix": token_hash[:12]}
    except Exception as e:
        logger.exception("Failed to invalidate token cache", token_prefix=token_hash[:12])
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            AUTH_TOKEN_INVALIDATION_FAILURE_COUNTER.labels(invalidation_type="token").inc()
            capture_exception(e)
            # Use the explicit exc_info tuple so stdlib logging attaches the original
            # Redis/invalidation traceback, not the current MaxRetriesExceededError context.
            logger.exception(
                "Auth token cache invalidation exhausted all retries",
                token_prefix=token_hash[:12],
                max_retries=self.max_retries,
                exc_info=(type(e), e, e.__traceback__),
            )
            raise


@shared_task(bind=True, max_retries=3, ignore_result=True)
def invalidate_user_tokens_task(self: Task, user_id: int) -> dict:
    """Invalidate all cached tokens for a user.

    Used as the async retry fallback for invalidate_user_tokens_sync.
    """
    try:
        token_auth_cache.invalidate_user_tokens(user_id)
        return {"status": "success", "user_id": user_id}
    except Exception as e:
        logger.exception("Failed to invalidate user tokens", user_id=user_id)
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            AUTH_TOKEN_INVALIDATION_FAILURE_COUNTER.labels(invalidation_type="user_tokens").inc()
            capture_exception(e)
            # Use the explicit exc_info tuple so stdlib logging attaches the original
            # Redis/invalidation traceback, not the current MaxRetriesExceededError context.
            logger.exception(
                "Auth token cache invalidation for user exhausted all retries",
                user_id=user_id,
                max_retries=self.max_retries,
                exc_info=(type(e), e, e.__traceback__),
            )
            raise


# --- Synchronous invalidation (called by signal handlers) ---


def invalidate_token_sync(token_hash: str) -> dict:
    """Synchronously invalidate a single token's cache entry with async retry fallback.

    Used for secret tokens, personal API keys, and project secret API keys —
    all are cached under their SHA256 hash in the same Redis key namespace.
    """
    return _sync_with_async_fallback(
        action=lambda: token_auth_cache.invalidate_token(token_hash),
        fallback_task=invalidate_token_cache_task,
        fallback_args=[token_hash],
        result_context={"token_prefix": token_hash[:12]},
    )


def invalidate_user_tokens_sync(user_id: int) -> dict:
    """Synchronously invalidate all cached tokens for a user with async retry fallback."""
    return _sync_with_async_fallback(
        action=lambda: token_auth_cache.invalidate_user_tokens(user_id),
        fallback_task=invalidate_user_tokens_task,
        fallback_args=[user_id],
        result_context={"user_id": user_id},
    )
