"""
Team discovery activity for LLM analytics workflows.

Provides dynamic team discovery that combines a guaranteed allowlist
with a configurable random sample of teams that have AI events.
"""

import math
import random
import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta

import structlog
import temporalio.activity
from temporalio.common import RetryPolicy

from posthog.temporal.common.heartbeat import Heartbeater

logger = structlog.get_logger(__name__)

# Guaranteed teams that are always included (the original hardcoded allowlist).
# Single source of truth for both clustering and summarization workflows.
GUARANTEED_TEAM_IDS: list[int] = [
    1,  # Local development
    2,  # Internal PostHog project
    # Dogfooding projects
    112495,
    148051,
    140227,
    237906,
    294356,
    21999,
    # External dogfooders
    117964,
    153418,
    109521,
    287645,
    306898,
    39143,
    240730,
]

# Default sample percentage for gradual rollout.
# 0.0 = only guaranteed teams, 0.1 = 10% of remaining, 1.0 = all teams with AI events.
SAMPLE_PERCENTAGE: float = 0.1

# How far back to look for teams with AI events. Intentionally wider than any
# individual workflow's data window (e.g. 7 days for clustering, 60 min for
# summarization) so we discover teams that have been active recently.
DISCOVERY_LOOKBACK_DAYS: int = 30

# Activity timeout for team discovery. Must exceed the underlying ClickHouse
# query's max_execution_time (5 min in CH_LLM_ANALYTICS_SETTINGS) plus retry
# overhead so the activity doesn't get killed before the fallback path runs.
DISCOVERY_ACTIVITY_TIMEOUT = timedelta(minutes=5)
DISCOVERY_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=2)


@dataclasses.dataclass
class TeamDiscoveryInput:
    lookback_days: int = DISCOVERY_LOOKBACK_DAYS
    sample_percentage: float = SAMPLE_PERCENTAGE


@temporalio.activity.defn
async def get_team_ids_for_llm_analytics(inputs: TeamDiscoveryInput) -> list[int]:
    """
    Discover teams for LLM analytics workflows.

    Returns guaranteed allowlist teams + a random sample of other teams with AI events.
    On failure, falls back to guaranteed teams only.
    """
    async with Heartbeater():
        guaranteed = set(GUARANTEED_TEAM_IDS)

        try:
            end = datetime.now(UTC)
            begin = end - timedelta(days=inputs.lookback_days)

            from posthog.tasks.llm_analytics_usage_report import get_teams_with_ai_events

            ai_event_teams = await asyncio.to_thread(get_teams_with_ai_events, begin, end)

            remaining = [t for t in ai_event_teams if t not in guaranteed]

            sample_size = math.ceil(len(remaining) * inputs.sample_percentage)
            sampled = random.sample(remaining, min(sample_size, len(remaining)))

            result = sorted(guaranteed | set(sampled))

            logger.info(
                "Team discovery completed",
                guaranteed_count=len(guaranteed),
                ai_event_teams_count=len(ai_event_teams),
                remaining_count=len(remaining),
                sampled_count=len(sampled),
                total_count=len(result),
                sample_percentage=inputs.sample_percentage,
            )

            return result

        except Exception:
            logger.warning(
                "Team discovery failed, falling back to guaranteed teams",
                exc_info=True,
                guaranteed_count=len(guaranteed),
            )
            return sorted(guaranteed)
