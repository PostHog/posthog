"""
Per-team organization entry that the Go ai-gateway reads for the organization's AI wallet.

Shape:
    Key: cache/teams/<team_id>/team_metadata/llm_gateway_org.json
    Body:
        {
            "version": 1,
            "team_id": 123,
            "organization_id": "0190...",
            "billing_period": {"start": "2026-10-01T00:00:00Z", "end": "2026-11-01T00:00:00Z"} | null,
            "ai_monthly_spend_limit_usd": "250.00" | null,
            "ai_low_balance_threshold_usd": "5.00" | null,
            "ai_automatic_reload_enabled": true | false,
            "customer_trust_scores": {"ai_credits": 10}
        }

Every team of an organization carries the same organization values. Admission reads the billed team's
entry, so one read gives the gateway the organization and its settings. The values come from billing's
status, which `BillingManager.update_org_details` keeps on the organization. A change there rewrites
every team of the organization, a new team gets its entry when PostHog creates it, and the hourly
refresh rewrites entries before they expire. A project moved to another organization gets its new
organization's entry when PostHog saves the move.

The gateway calls billing once when the balance drops below the threshold, then waits for the balance to
rise. When `ai_automatic_reload_enabled` turns on, it calls billing again.
"""

import os
from typing import Any

from django.conf import settings
from django.db import OperationalError

import structlog

from posthog.caching.ai_gateway_redis_cache import AI_GATEWAY_DEDICATED_CACHE_ALIAS
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.storage.cache_expiry_manager import (
    CacheRefreshCounts,
    refresh_expiring_caches as refresh_generic,
)
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType
from posthog.storage.hypercache_manager import (
    HyperCacheManagementConfig,
    get_cache_stats as _generic_cache_stats,
)

logger = structlog.get_logger(__name__)

LLM_GATEWAY_ORG_VERSION = 1
LLM_GATEWAY_ORG_CACHE_TTL = int(os.environ.get("LLM_GATEWAY_ORG_CACHE_TTL", str(60 * 60 * 24 * 7)))
LLM_GATEWAY_ORG_CACHE_MISS_TTL = int(os.environ.get("LLM_GATEWAY_ORG_CACHE_MISS_TTL", str(60 * 60)))
LLM_GATEWAY_ORG_CACHE_EXPIRY_SORTED_SET = "llm_gateway_org_cache_expiry"

LLM_GATEWAY_ORG_FIELDS = ("id", "usage", "customer_trust_scores")


def llm_gateway_org_values(organization: Organization) -> dict[str, Any]:
    """The organization's part of the entry, the same for each of its teams."""
    usage = organization.usage or {}
    period = usage.get("period")
    return {
        "organization_id": str(organization.id),
        "billing_period": {"start": period[0], "end": period[1]} if period and len(period) == 2 else None,
        "ai_monthly_spend_limit_usd": usage.get("ai_monthly_spend_limit_usd"),
        "ai_low_balance_threshold_usd": usage.get("ai_low_balance_threshold_usd"),
        "ai_automatic_reload_enabled": usage.get("ai_automatic_reload_enabled") is True,
        "customer_trust_scores": organization.customer_trust_scores or {},
    }


def _entry(team_id: int, organization: Organization) -> dict[str, Any]:
    return {"version": LLM_GATEWAY_ORG_VERSION, "team_id": team_id, **llm_gateway_org_values(organization)}


def _organizations(organization_ids: set[Any]) -> dict[Any, Organization]:
    return {org.id: org for org in Organization.objects.filter(id__in=organization_ids).only(*LLM_GATEWAY_ORG_FIELDS)}


def _batch_load_llm_gateway_org(teams: list[Team]) -> dict[int, dict[str, Any]]:
    organizations = _organizations({team.organization_id for team in teams})
    return {
        team.id: _entry(team.id, organizations[team.organization_id])
        for team in teams
        if team.organization_id in organizations
    }


def _load_llm_gateway_org(team_key: KeyType) -> dict[str, Any] | HyperCacheStoreMissing:
    # Only a missing team or a database error soft-fails, as in the policy cache: any other error is a
    # bug that a cached miss would hide from every gateway call for the team.
    try:
        team = HyperCache.team_from_key(team_key)
        organization = Organization.objects.only(*LLM_GATEWAY_ORG_FIELDS).get(id=team.organization_id)
        return _entry(team.id, organization)
    except (Team.DoesNotExist, Organization.DoesNotExist):
        return HyperCacheStoreMissing()
    except OperationalError as e:
        logger.exception("Database error loading the llm-gateway organization entry", error_type=type(e).__name__)
        return HyperCacheStoreMissing()


team_llm_gateway_org_hypercache = HyperCache(
    namespace="team_metadata",
    value="llm_gateway_org.json",
    token_based=False,
    load_fn=_load_llm_gateway_org,
    batch_load_fn=_batch_load_llm_gateway_org,
    cache_ttl=LLM_GATEWAY_ORG_CACHE_TTL,
    cache_miss_ttl=LLM_GATEWAY_ORG_CACHE_MISS_TTL,
    cache_alias=(AI_GATEWAY_DEDICATED_CACHE_ALIAS if AI_GATEWAY_DEDICATED_CACHE_ALIAS in settings.CACHES else None),
    expiry_sorted_set_key=LLM_GATEWAY_ORG_CACHE_EXPIRY_SORTED_SET,
    s3_enabled=False,
)


def get_team_llm_gateway_org(team: Team | int) -> dict[str, Any] | None:
    return team_llm_gateway_org_hypercache.get_from_cache(team)


def update_team_llm_gateway_org_cache(team: Team | int, ttl: int | None = None) -> bool:
    success = team_llm_gateway_org_hypercache.update_cache(team, ttl=ttl)
    if not success:
        logger.warning("Failed to update the llm-gateway organization entry", team_id=getattr(team, "id", team))
    return success


def update_organization_llm_gateway_org_cache(organization_id: Any) -> int:
    """Rewrite the entry of every team of the organization, child environments included. Returns how many."""
    organization = Organization.objects.only(*LLM_GATEWAY_ORG_FIELDS).filter(id=organization_id).first()
    if organization is None:
        return 0
    written = 0
    for team in Team.objects.filter(organization_id=organization.id).only("id", "organization_id"):
        team_llm_gateway_org_hypercache.set_cache_value(team, _entry(team.id, organization))
        written += 1
    return written


def clear_team_llm_gateway_org_cache(team: Team | int, kinds: list[str] | None = None) -> None:
    team_llm_gateway_org_hypercache.clear_cache(team, kinds=kinds)


LLM_GATEWAY_ORG_HYPERCACHE_MANAGEMENT_CONFIG = HyperCacheManagementConfig(
    hypercache=team_llm_gateway_org_hypercache,
    update_fn=update_team_llm_gateway_org_cache,
    cache_name="llm_gateway_org",
    # The batch loader reads the organization itself, so the team only needs its ids. The project id keeps
    # the refresh's select_related join valid.
    refresh_only_fields=["id", "organization_id", "project_id"],
)


def refresh_expiring_caches(ttl_threshold_hours: int = 24, limit: int = 5000) -> CacheRefreshCounts:
    return refresh_generic(LLM_GATEWAY_ORG_HYPERCACHE_MANAGEMENT_CONFIG, ttl_threshold_hours, limit)


def get_cache_stats() -> dict[str, Any]:
    return _generic_cache_stats(LLM_GATEWAY_ORG_HYPERCACHE_MANAGEMENT_CONFIG)
