"""
Per-token auth cache with targeted invalidation.

Rust populates cache entries on first use (lazy). Python signal handlers
perform targeted invalidation when cached tokens become invalid.

Cache keys (Rust writes, Python only deletes):
  posthog:auth_token:{token_hash}        → token metadata
"""

import redis as redis_lib
import structlog

from posthog.models.personal_api_key import SHA256_HASH_PREFIX, PersonalAPIKey

logger = structlog.get_logger(__name__)

# Cache key prefix — must match the prefix used by the Rust feature-flags service
TOKEN_CACHE_PREFIX = "posthog:auth_token:"


def _get_redis_client() -> redis_lib.Redis:
    """Get a direct redis-py client for the flags Redis (falls back to shared)."""
    from django.conf import settings

    from posthog.redis import get_client

    return get_client(settings.FLAGS_REDIS_URL)


class TokenAuthCache:
    """Per-token auth cache with targeted invalidation."""

    def __init__(self, redis_client: redis_lib.Redis | None = None):
        self._redis_client = redis_client

    @property
    def is_configured(self) -> bool:
        if self._redis_client is not None:
            return True
        from django.conf import settings

        return bool(settings.FLAGS_REDIS_URL)

    @property
    def redis(self) -> redis_lib.Redis:
        if self._redis_client is None:
            self._redis_client = _get_redis_client()
        return self._redis_client

    def invalidate_token(self, token_hash: str) -> None:
        """Invalidate a single token's cache entry."""
        if not self.is_configured:
            return

        cache_key = f"{TOKEN_CACHE_PREFIX}{token_hash}"

        deleted = self.redis.delete(cache_key)
        if deleted:
            logger.info("Invalidated auth token cache entry", token_hash_prefix=token_hash[:12])
        else:
            logger.debug("Auth token cache entry not found", token_hash_prefix=token_hash[:12])

    def invalidate_tokens(self, token_hashes: list[str]) -> None:
        """Invalidate multiple token cache entries in a single Redis call."""
        if not self.is_configured:
            return

        if not token_hashes:
            return

        cache_keys = [f"{TOKEN_CACHE_PREFIX}{th}" for th in token_hashes]
        deleted = self.redis.delete(*cache_keys)
        logger.info("Invalidated auth token cache entries", count=deleted)

    def invalidate_user_tokens(self, user_id: int) -> None:
        """Invalidate all cached tokens for a user via DB lookup.

        Rust caches all personal API keys under their sha256 hash.
        The sha256$ filter is a defensive guard against any legacy rows
        that predate the current hashing scheme.
        """
        # Guard here (not just in invalidate_tokens) to skip the DB query
        if not self.is_configured:
            return

        secure_values: list[str] = list(
            PersonalAPIKey.objects.filter(user_id=user_id, secure_value__startswith=SHA256_HASH_PREFIX).values_list(
                "secure_value", flat=True
            )  # type: ignore[arg-type]  # filter guarantees non-null
        )

        if not secure_values:
            return

        self.invalidate_tokens(secure_values)
        logger.info("Invalidated tokens for user via DB", user_id=user_id, tokens_invalidated=len(secure_values))


# Global instance
token_auth_cache = TokenAuthCache()
