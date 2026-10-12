from django.conf import settings

from posthog.caching.ai_gateway_redis_cache import AI_GATEWAY_DEDICATED_CACHE_ALIAS
from posthog.models.team.team import Team
from posthog.storage.cache_expiry_manager import CacheRefreshCounts, refresh_expiring_caches
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType
from posthog.storage.hypercache_manager import HyperCacheManagementConfig


def _load_account_trust(team_key: KeyType) -> dict[str, object] | HyperCacheStoreMissing:
    try:
        team = HyperCache.team_from_key(team_key)
    except Team.DoesNotExist:
        return HyperCacheStoreMissing()
    row = (
        Team.objects.filter(id=team.id)
        .values("id", "organization__created_at", "organization__customer_trust_scores")
        .first()
    )
    if row is None:
        return HyperCacheStoreMissing()
    return {
        "team_id": row["id"],
        "organization_created_at": row["organization__created_at"].isoformat(),
        "customer_trust_scores": row["organization__customer_trust_scores"],
    }


team_llm_gateway_account_trust_hypercache = HyperCache(
    namespace="team_metadata",
    value="llm_gateway_account_trust.json",
    token_based=False,
    load_fn=_load_account_trust,
    cache_ttl=7 * 24 * 60 * 60,
    cache_miss_ttl=60,
    cache_alias=(AI_GATEWAY_DEDICATED_CACHE_ALIAS if AI_GATEWAY_DEDICATED_CACHE_ALIAS in settings.CACHES else None),
    s3_enabled=False,
    expiry_sorted_set_key="llm_gateway_account_trust_cache_expiry",
)


def update_team_account_trust(team: Team | int, ttl: int | None = None) -> bool:
    return team_llm_gateway_account_trust_hypercache.update_cache(team, ttl=ttl)


def clear_team_account_trust(team: Team | int) -> None:
    team_llm_gateway_account_trust_hypercache.delete_cache_entry(team, kinds=["redis"])


def invalidate_team_account_trust(team: Team) -> None:
    # Keep invalidated entries in the refresh queue if task delivery fails.
    team_llm_gateway_account_trust_hypercache.set_cache_value_redis_only(
        team, {"team_id": team.id}, ttl=60, track_expiry=True
    )


def refresh_account_trust_caches() -> CacheRefreshCounts:
    return refresh_expiring_caches(
        HyperCacheManagementConfig(
            hypercache=team_llm_gateway_account_trust_hypercache,
            update_fn=update_team_account_trust,
            cache_name="llm_gateway_account_trust",
            refresh_only_fields=["id", "organization_id", "project_id"],
        ),
        ttl_threshold_hours=24,
    )
