"""Precomputation for the Bot Analytics tab on Web Analytics.

Bot trends are dominated by a small set of date ranges (last 7 / 14 / 30 days)
and a fixed query shape: count of `$pageview`/`$screen`/`$http_log` events with
`$virt_is_bot=true`, broken down by one of four dimensions (crawler name,
traffic category, host, path). The raw-events scan is expensive at our scale,
so we lazy-compute hourly buckets per breakdown and read from
`preaggregation_results` at runtime.

See `products/analytics_platform/backend/lazy_computation/README.md` for the
underlying framework.
"""

from posthog.hogql_queries.web_analytics.bot_analytics.precomputation import (
    BOT_ANALYTICS_EVENTS,
    BOT_TRENDS_BREAKDOWN_FIELDS,
    BotTrendsBreakdown,
    bot_trends_select_query,
    ensure_bot_analytics_precomputed,
)

__all__ = [
    "BOT_ANALYTICS_EVENTS",
    "BOT_TRENDS_BREAKDOWN_FIELDS",
    "BotTrendsBreakdown",
    "bot_trends_select_query",
    "ensure_bot_analytics_precomputed",
]
