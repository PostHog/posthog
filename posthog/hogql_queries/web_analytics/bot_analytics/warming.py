from datetime import UTC, datetime, timedelta

import structlog

from posthog.hogql_queries.web_analytics.bot_analytics.precomputation import (
    BotTrendsBreakdown,
    ensure_bot_analytics_precomputed,
)
from posthog.models.team import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult

logger = structlog.get_logger(__name__)

# We warm 30 days because the bot tab's three preset ranges (7 / 14 / 30 days)
# all read from the same precomputed data — warming the longest range covers
# the other two for free.
BOT_TRENDS_WARM_DAYS = 30


def warm_bot_analytics_for_team(
    team: Team,
    days: int = BOT_TRENDS_WARM_DAYS,
    breakdowns: tuple[BotTrendsBreakdown, ...] = tuple(BotTrendsBreakdown),
) -> dict[BotTrendsBreakdown, LazyComputationResult]:
    """Trigger precomputation for the bot trends tab for a single team.

    Walks each breakdown sequentially. Failures are logged but do not abort
    the remaining breakdowns — partial warmth is better than no warmth.
    """
    now = datetime.now(UTC)
    date_to = now
    date_from = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

    results: dict[BotTrendsBreakdown, LazyComputationResult] = {}
    for breakdown in breakdowns:
        try:
            results[breakdown] = ensure_bot_analytics_precomputed(
                team=team,
                breakdown=breakdown,
                date_from=date_from,
                date_to=date_to,
            )
        except Exception:
            # Per-breakdown failure shouldn't tank warming for the rest of
            # the team. The lazy executor logs the underlying CH error.
            logger.exception(
                "bot_analytics_warming_failed",
                team_id=team.id,
                breakdown=str(breakdown),
            )

    return results
