"""
Targeted invalidation tasks for the per-token auth cache.

These tasks are triggered by Django signal handlers when tokens become
invalid or their cached metadata is stale.
"""

import structlog
from celery import Task, shared_task

from posthog.storage.team_access_cache import token_auth_cache

logger = structlog.get_logger(__name__)


@shared_task(bind=True, max_retries=3)
def invalidate_personal_api_key_cache_task(self: Task, secure_value: str, user_id: int | None = None) -> dict:
    """
    Invalidate a single personal API key's cache entry.

    Triggered when a PersonalAPIKey is created, updated, or deleted.

    Rust caches personal API keys under their sha256 hash. For legacy PBKDF2
    keys, the DB secure_value won't match the cache key, so we fall back to
    invalidating all tokens for the user via DB lookup.
    """
    try:
        is_legacy_hash = not secure_value.startswith("sha256$")
        if is_legacy_hash and user_id is not None:
            token_auth_cache.invalidate_user_tokens(user_id)
        elif is_legacy_hash:
            # Legacy PBKDF2 key with no user_id — cannot invalidate by token hash (Rust
            # only caches SHA256 keys) and have no user to look up via DB.
            # This is a safe no-op: the key was never cached under this hash.
            logger.warning(
                "Cannot invalidate legacy PBKDF2 key without user_id; skipping",
                secure_value_prefix=secure_value[:12],
            )
            return {"status": "skipped", "reason": "legacy_key_no_user_id", "secure_value_prefix": secure_value[:12]}
        else:
            token_auth_cache.invalidate_token(secure_value)
        return {"status": "success", "secure_value_prefix": secure_value[:12]}
    except Exception as e:
        logger.exception("Failed to invalidate personal API key cache", secure_value_prefix=secure_value[:12])
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3)
def invalidate_user_tokens_task(self: Task, user_id: int) -> dict:
    """
    Invalidate all cached tokens for a user.

    Triggered when a user is activated, deactivated, or org membership changes.
    """
    try:
        token_auth_cache.invalidate_user_tokens(user_id)
        return {"status": "success", "user_id": user_id}
    except Exception as e:
        logger.exception("Failed to invalidate user tokens", user_id=user_id)
        raise self.retry(exc=e)


def invalidate_user_tokens_sync(user_id: int) -> dict:
    """
    Synchronously invalidate all cached tokens for a user.

    Used for security-critical paths (e.g., user deactivation) where
    we cannot tolerate Celery queue delay before revocation takes effect.

    Calls the cache directly instead of the Celery task to avoid
    unexpected Retry exceptions in the synchronous call path.

    If the sync attempt fails (e.g., brief Redis blip), we schedule an
    async retry as a safety net. Without this, a failed invalidation
    leaves the deactivated user's cached token valid for up to 30 days
    (the cache TTL), since there is no periodic re-warming task to
    catch stale entries.
    """
    try:
        token_auth_cache.invalidate_user_tokens(user_id)
        return {"status": "success", "user_id": user_id}
    except Exception:
        logger.exception("Sync invalidation failed, scheduling async retry", user_id=user_id)
        try:
            invalidate_user_tokens_task.apply_async(args=[user_id], countdown=5)
        except Exception:
            logger.exception("Failed to schedule async retry", user_id=user_id)
        return {"status": "failure", "user_id": user_id}
