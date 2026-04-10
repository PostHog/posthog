"""
Per-token auth cache for the /flags/definitions service with targeted invalidation.

Rust populates cache entries on first use (lazy). Python signal handlers
perform targeted invalidation when cached tokens become invalid.

Cache keys (Rust writes, Python only deletes):
  posthog:auth_token:{token_hash}        → token metadata
"""

from __future__ import annotations

from django.db.models import Q

import redis as redis_lib
import structlog

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import SHA256_HASH_PREFIX, hash_key_value

logger = structlog.get_logger(__name__)

# Cache key prefix — must match the prefix used by the Rust /flags/definitions service
TOKEN_CACHE_PREFIX = "posthog:auth_token:"


def _get_redis_client() -> redis_lib.Redis:
    """Get a direct redis-py client for the flags Redis (falls back to shared)."""
    from django.conf import settings

    from posthog.redis import get_client

    return get_client(settings.FLAGS_REDIS_URL)


class TokenAuthCache:
    """Per-token auth cache for the /flags/definitions service with targeted invalidation."""

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

    def invalidate_team_tokens(
        self,
        team_id: int,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Invalidate all cached flags-service auth tokens for a team.

        Clears Redis cache entries so the Rust /flags/definitions service re-validates
        against Postgres on the next request. Does not revoke the tokens themselves.
        Covers team secret tokens, project secret API keys, and personal API keys
        that have access to the team.

        When dry_run=True, collects and counts tokens but skips Redis deletion.

        Returns counts of tokens found per category.
        """
        # Guard here (not just in invalidate_tokens) to skip the DB queries
        if not dry_run and not self.is_configured:
            return {"secret_tokens": 0, "project_secret_keys": 0, "personal_keys": 0, "total": 0}

        team = Team.objects.only("id", "secret_api_token", "secret_api_token_backup", "organization_id").get(id=team_id)

        all_hashes: list[str] = []

        # 1. Team secret tokens
        secret_token_hashes = [
            hash_key_value(token, mode="sha256")
            for token in (team.secret_api_token, team.secret_api_token_backup)
            if token
        ]
        all_hashes.extend(secret_token_hashes)

        # 2. Project Secret API Keys
        psak_secure_values: list[str] = list(
            ProjectSecretAPIKey.objects.filter(team_id=team_id, secure_value__isnull=False).values_list(
                "secure_value", flat=True
            )  # type: ignore[arg-type]  # filter guarantees non-null
        )
        all_hashes.extend(psak_secure_values)

        # 3. Personal API Keys that could access this team
        org_id = str(team.organization_id)
        pak_secure_values: list[str] = list(
            PersonalAPIKey.objects.filter(
                user__organization_membership__organization_id=team.organization_id,
                secure_value__startswith=SHA256_HASH_PREFIX,
            )
            .filter(
                Q(scoped_teams__isnull=True) | Q(scoped_teams=[]) | Q(scoped_teams__contains=[team_id]),
                Q(scoped_organizations__isnull=True)
                | Q(scoped_organizations=[])
                | Q(scoped_organizations__contains=[org_id]),
            )
            .values_list("secure_value", flat=True)  # type: ignore[arg-type]  # startswith filter guarantees non-null
        )
        all_hashes.extend(pak_secure_values)

        if all_hashes and not dry_run:
            self.invalidate_tokens(all_hashes)

        counts = {
            "secret_tokens": len(secret_token_hashes),
            "project_secret_keys": len(psak_secure_values),
            "personal_keys": len(pak_secure_values),
            "total": len(all_hashes),
        }
        if not dry_run:
            logger.info("Invalidated team tokens", team_id=team_id, **counts)
        return counts


# Global instance
token_auth_cache = TokenAuthCache()
