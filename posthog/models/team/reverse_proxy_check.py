from typing import TYPE_CHECKING

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.utils import get_safe_cache, safe_cache_set

if TYPE_CHECKING:
    from posthog.models.team import Team

# A team without a proxy may set one up at any time, so a negative answer expires quickly.
NO_REVERSE_PROXY_CACHE_TTL_SECONDS = 60 * 10
# A detected proxy rarely goes away, so a positive answer is cached for longer.
HAS_REVERSE_PROXY_CACHE_TTL_SECONDS = 60 * 60 * 24

REVERSE_PROXY_QUERY = """
SELECT DISTINCT properties.$lib_custom_api_host AS lib_custom_api_host
FROM events
WHERE timestamp >= now() - INTERVAL 1 DAY
AND timestamp <= now()
AND properties.$lib_custom_api_host IS NOT NULL
AND event IN ('$pageview', '$screen')
LIMIT 10
"""


def _cache_key(team_id: int) -> str:
    return f"team_has_reverse_proxy:{team_id}"


def get_cached_has_reverse_proxy(team: "Team") -> bool | None:
    """Answer from the cache only, so it never queries ClickHouse. None means unknown."""
    cached = get_safe_cache(_cache_key(team.pk))
    return cached if isinstance(cached, bool) else None


def get_has_reverse_proxy(team: "Team") -> bool:
    cached = get_cached_has_reverse_proxy(team)
    if cached is not None:
        return cached

    with tags_context(product=Product.PLATFORM_AND_SUPPORT, team_id=team.pk):
        response = execute_hogql_query(REVERSE_PROXY_QUERY, team=team, query_type="reverse_proxy_check")
    has_reverse_proxy = any(row[0] for row in response.results or [])

    ttl = HAS_REVERSE_PROXY_CACHE_TTL_SECONDS if has_reverse_proxy else NO_REVERSE_PROXY_CACHE_TTL_SECONDS
    safe_cache_set(_cache_key(team.pk), has_reverse_proxy, timeout=ttl)
    return has_reverse_proxy
