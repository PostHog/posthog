"""
LLM gateway policy HyperCache — purpose-built cache projection for the Go
llm-gateway service.

Shape:
    Key: cache/team_tokens/<api_token>/team_metadata/llm_gateway_policy.json
    Body:
        {
            "id": 123,
            "api_token": "phc_...",
            "llm_gateway_allowed_models": ["openai/gpt-4o", ...] | null,
            "llm_gateway_tier": "free" | "pro" | "enterprise" | null,
            "llm_gateway_revoked_at": "2026-05-20T12:34:56+00:00" | null
        }

The blob is written to its own cache key (sibling to full_metadata.json) so the
flags-pipeline consumers of team_metadata are not affected by additions here.
Null values are normalized by the consumer: empty allowlist, free tier, not
revoked. No backfill is required when these columns are first added to the
Team model.
"""

import os
from typing import Any

from django.conf import settings
from django.db import transaction

import structlog

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.models.team.team import Team
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType

logger = structlog.get_logger(__name__)


LLM_GATEWAY_POLICY_CACHE_TTL = int(os.environ.get("LLM_GATEWAY_POLICY_CACHE_TTL", str(60 * 60 * 24 * 7)))
LLM_GATEWAY_POLICY_CACHE_MISS_TTL = int(os.environ.get("LLM_GATEWAY_POLICY_CACHE_MISS_TTL", str(60 * 60 * 24)))

LLM_GATEWAY_POLICY_FIELDS = [
    "id",
    "api_token",
    "llm_gateway_allowed_models",
    "llm_gateway_tier",
    "llm_gateway_revoked_at",
]


def _serialize_team_to_llm_gateway_policy(team: Team) -> dict[str, Any]:
    """Project a Team into the JSON shape the Go llm-gateway consumes."""
    return {
        "id": team.id,
        "api_token": team.api_token,
        "llm_gateway_allowed_models": team.llm_gateway_allowed_models,
        "llm_gateway_tier": team.llm_gateway_tier,
        "llm_gateway_revoked_at": (team.llm_gateway_revoked_at.isoformat() if team.llm_gateway_revoked_at else None),
    }


def _batch_load_llm_gateway_policy(teams: list[Team]) -> dict[int, dict[str, Any]]:
    return {team.id: _serialize_team_to_llm_gateway_policy(team) for team in teams}


def _load_llm_gateway_policy(team_key: KeyType) -> dict[str, Any] | HyperCacheStoreMissing:
    try:
        with transaction.atomic():
            team = HyperCache.team_from_key(team_key)
            return _serialize_team_to_llm_gateway_policy(team)
    except Team.DoesNotExist:
        logger.debug("Team not found for llm-gateway policy lookup")
        return HyperCacheStoreMissing()
    except Exception as e:
        logger.exception(
            "Error loading llm-gateway policy",
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
    cache_alias=FLAGS_DEDICATED_CACHE_ALIAS if FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES else None,
)


def get_team_llm_gateway_policy(team: Team | str | int) -> dict[str, Any] | None:
    return team_llm_gateway_policy_hypercache.get_from_cache(team)


def update_team_llm_gateway_policy_cache(team: Team | str | int, ttl: int | None = None) -> bool:
    success = team_llm_gateway_policy_hypercache.update_cache(team, ttl=ttl)
    if not success:
        team_id = team.id if isinstance(team, Team) else "unknown"
        logger.warning("Failed to update llm-gateway policy cache", team_id=team_id)
    return success


def clear_team_llm_gateway_policy_cache(team: Team | str | int, kinds: list[str] | None = None) -> None:
    team_llm_gateway_policy_hypercache.clear_cache(team, kinds=kinds)
