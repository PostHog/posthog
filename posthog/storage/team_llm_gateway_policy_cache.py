"""
LLM gateway policy HyperCache — purpose-built cache projection for the Go
llm-gateway service.

Shape:
    Key: cache/team_tokens/<api_token>/team_metadata/llm_gateway_policy.json
    Body:
        {
            "id": 123,
            "api_token": "phc_...",
            "llm_gateway_enabled_at": "2026-05-29T20:46:30+00:00" | null,
            "llm_gateway_revoked_at": "2026-05-20T12:34:56+00:00" | null
        }

The blob is written to its own cache key (sibling to full_metadata.json) so the
flags-pipeline consumers of team_metadata are not affected by additions here.
The gateway admits a team only when enabled_at is set and revoked_at is null;
revoke wins over enable. Null enabled_at = not enrolled (default-deny); null
revoked_at = not revoked. Nullable defaults mean no backfill on schema add.
"""

import os
from typing import Any

from django.conf import settings
from django.db import OperationalError

import structlog

from posthog.caching.ai_gateway_redis_cache import AI_GATEWAY_DEDICATED_CACHE_ALIAS
from posthog.models.team.team import Team
from posthog.storage.cache_expiry_manager import refresh_expiring_caches as refresh_generic
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType
from posthog.storage.hypercache_manager import (
    HyperCacheManagementConfig,
    get_cache_stats as _generic_cache_stats,
)

logger = structlog.get_logger(__name__)


LLM_GATEWAY_POLICY_CACHE_TTL = int(os.environ.get("LLM_GATEWAY_POLICY_CACHE_TTL", str(60 * 60 * 24 * 7)))
LLM_GATEWAY_POLICY_CACHE_MISS_TTL = int(os.environ.get("LLM_GATEWAY_POLICY_CACHE_MISS_TTL", str(60 * 60 * 24)))

LLM_GATEWAY_POLICY_CACHE_EXPIRY_SORTED_SET = "llm_gateway_policy_cache_expiry"

LLM_GATEWAY_POLICY_FIELDS = [
    "id",
    "api_token",
    "llm_gateway_enabled_at",
    "llm_gateway_revoked_at",
]


def _serialize_team_to_llm_gateway_policy(team: Team) -> dict[str, Any]:
    """Project a Team into the JSON shape the Go llm-gateway consumes."""
    return {
        "id": team.id,
        "api_token": team.api_token,
        "llm_gateway_enabled_at": (team.llm_gateway_enabled_at.isoformat() if team.llm_gateway_enabled_at else None),
        "llm_gateway_revoked_at": (team.llm_gateway_revoked_at.isoformat() if team.llm_gateway_revoked_at else None),
    }


def _batch_load_llm_gateway_policy(teams: list[Team]) -> dict[int, dict[str, Any]]:
    return {team.id: _serialize_team_to_llm_gateway_policy(team) for team in teams}


def _load_llm_gateway_policy(team_key: KeyType) -> dict[str, Any] | HyperCacheStoreMissing:
    # Narrow except clause: catching Exception would turn any bug (TypeError,
    # AttributeError, etc.) into a 24h negative-cache entry that 401s every
    # gateway request for the team. Only Team.DoesNotExist (genuine miss) and
    # OperationalError (expected transient DB failure) soft-fail. Anything
    # else propagates so the cache can retry on the next request.
    try:
        team = HyperCache.team_from_key(team_key)
        return _serialize_team_to_llm_gateway_policy(team)
    except Team.DoesNotExist:
        logger.debug("Team not found for llm-gateway policy lookup")
        return HyperCacheStoreMissing()
    except OperationalError as e:
        logger.exception(
            "Database error loading llm-gateway policy",
            error_type=type(e).__name__,
            team_key_type=type(team_key).__name__,
        )
        return HyperCacheStoreMissing()


team_llm_gateway_policy_hypercache = HyperCache(
    namespace="team_metadata",
    value="llm_gateway_policy.json",
    token_based=True,
    load_fn=_load_llm_gateway_policy,
    batch_load_fn=_batch_load_llm_gateway_policy,
    cache_ttl=LLM_GATEWAY_POLICY_CACHE_TTL,
    cache_miss_ttl=LLM_GATEWAY_POLICY_CACHE_MISS_TTL,
    cache_alias=(AI_GATEWAY_DEDICATED_CACHE_ALIAS if AI_GATEWAY_DEDICATED_CACHE_ALIAS in settings.CACHES else None),
    expiry_sorted_set_key=LLM_GATEWAY_POLICY_CACHE_EXPIRY_SORTED_SET,
)


def get_team_llm_gateway_policy(team: Team | str | int) -> dict[str, Any] | None:
    return team_llm_gateway_policy_hypercache.get_from_cache(team)


def get_team_llm_gateway_policy_from_redis(team: Team) -> tuple[dict[str, Any] | None, str]:
    """Redis-only probe, no fallback or write-back. Source: "redis_hit",
    "redis_negative" (24h deny sentinel), or "absent"."""
    results = team_llm_gateway_policy_hypercache.batch_get_from_cache([team])
    data, source, _etag = results[team.id]
    if source == "miss":
        return None, "absent"
    if data is None:
        return None, "redis_negative"
    return data, "redis_hit"


def update_team_llm_gateway_policy_cache(team: Team | str | int, ttl: int | None = None) -> bool:
    success = team_llm_gateway_policy_hypercache.update_cache(team, ttl=ttl)
    if not success:
        team_id = team.id if isinstance(team, Team) else "unknown"
        logger.warning("Failed to update llm-gateway policy cache", team_id=team_id)
    return success


def clear_team_llm_gateway_policy_cache(team: Team | str | int, kinds: list[str] | None = None) -> None:
    team_llm_gateway_policy_hypercache.clear_cache(team, kinds=kinds)


LLM_GATEWAY_POLICY_HYPERCACHE_MANAGEMENT_CONFIG = HyperCacheManagementConfig(
    hypercache=team_llm_gateway_policy_hypercache,
    update_fn=update_team_llm_gateway_policy_cache,
    cache_name="llm_gateway_policy",
    # The refresh only projects these columns; narrowing the SELECT keeps it resilient
    # to newly added Team columns the read replica may not have applied yet. The FK ids
    # are included so the (unused) organization/project select_related join stays valid.
    refresh_only_fields=[*LLM_GATEWAY_POLICY_FIELDS, "project_id", "organization_id"],
)


def refresh_expiring_caches(ttl_threshold_hours: int = 24, limit: int = 5000) -> tuple[int, int]:
    """
    Refresh policy caches whose TTL falls below the threshold. Mirrors the
    team_metadata refresh pipeline so the cache stays warm under a growing
    team pool instead of relying on lazy DB lookups when entries expire.
    """
    return refresh_generic(LLM_GATEWAY_POLICY_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours, limit)


def get_cache_stats() -> dict[str, Any]:
    """Coverage/TTL stats for the policy cache; also pushes Prometheus gauges."""
    return _generic_cache_stats(LLM_GATEWAY_POLICY_HYPERCACHE_MANAGEMENT_CONFIG)
