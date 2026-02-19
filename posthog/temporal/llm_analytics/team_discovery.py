"""
Team discovery activity for LLM analytics workflows.

Provides dynamic team discovery that combines a guaranteed allowlist
with a configurable random sample of teams that have AI events.

Config is read from the `llm-analytics-clustering-workflows` feature flag
payload so it can be changed from the PostHog UI without a deploy.
Falls back to hardcoded defaults when the payload is missing or invalid.
"""

import math
import random
import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta

import structlog
import posthoganalytics
import temporalio.activity
from temporalio.common import RetryPolicy

from posthog.temporal.common.heartbeat import Heartbeater

logger = structlog.get_logger(__name__)

FEATURE_FLAG_KEY = "llm-analytics-clustering-workflows"

# Default fallbacks — used when the feature flag payload is missing or invalid.
DEFAULT_GUARANTEED_TEAM_IDS: list[int] = [
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
# 0.0 = only guaranteed teams, 0.5 = 50% of remaining, 1.0 = all teams with AI events.
DEFAULT_SAMPLE_PERCENTAGE: float = 0.5
DEFAULT_DISCOVERY_LOOKBACK_DAYS: int = 30

# Backward-compatible aliases for coordinator imports.
# Coordinators use these only in the last-resort fallback path (when the
# activity itself fails), so pointing at defaults is fine.
GUARANTEED_TEAM_IDS = DEFAULT_GUARANTEED_TEAM_IDS
SAMPLE_PERCENTAGE = DEFAULT_SAMPLE_PERCENTAGE
DISCOVERY_LOOKBACK_DAYS = DEFAULT_DISCOVERY_LOOKBACK_DAYS


@dataclasses.dataclass
class LLMAWorkflowConfig:
    guaranteed_team_ids: list[int]
    sample_percentage: float
    discovery_lookback_days: int


def _get_llma_workflow_config() -> LLMAWorkflowConfig:
    """Read LLMA team-discovery config from the feature flag payload, falling back to defaults."""
    try:
        payload: dict | None = posthoganalytics.get_feature_flag_payload(  # type: ignore[assignment]
            FEATURE_FLAG_KEY, "internal_llma_team_discovery"
        )

        if not isinstance(payload, dict):
            logger.info("No valid FF payload, using defaults", payload_type=type(payload).__name__)
            return LLMAWorkflowConfig(
                guaranteed_team_ids=DEFAULT_GUARANTEED_TEAM_IDS,
                sample_percentage=DEFAULT_SAMPLE_PERCENTAGE,
                discovery_lookback_days=DEFAULT_DISCOVERY_LOOKBACK_DAYS,
            )

        guaranteed = payload.get("guaranteed_team_ids", DEFAULT_GUARANTEED_TEAM_IDS)
        if not isinstance(guaranteed, list) or not all(isinstance(t, int) for t in guaranteed):
            guaranteed = DEFAULT_GUARANTEED_TEAM_IDS

        sample_pct = payload.get("sample_percentage", DEFAULT_SAMPLE_PERCENTAGE)
        if not isinstance(sample_pct, (int, float)) or not (0.0 <= float(sample_pct) <= 1.0):
            sample_pct = DEFAULT_SAMPLE_PERCENTAGE

        lookback = payload.get("discovery_lookback_days", DEFAULT_DISCOVERY_LOOKBACK_DAYS)
        if not isinstance(lookback, int) or lookback <= 0:
            lookback = DEFAULT_DISCOVERY_LOOKBACK_DAYS

        logger.info(
            "Loaded LLMA config from feature flag",
            guaranteed_count=len(guaranteed),
            sample_percentage=sample_pct,
            discovery_lookback_days=lookback,
        )

        return LLMAWorkflowConfig(
            guaranteed_team_ids=guaranteed,
            sample_percentage=float(sample_pct),
            discovery_lookback_days=lookback,
        )
    except Exception:
        logger.warning("Failed to read LLMA config from feature flag, using defaults", exc_info=True)
        return LLMAWorkflowConfig(
            guaranteed_team_ids=DEFAULT_GUARANTEED_TEAM_IDS,
            sample_percentage=DEFAULT_SAMPLE_PERCENTAGE,
            discovery_lookback_days=DEFAULT_DISCOVERY_LOOKBACK_DAYS,
        )


# Activity timeout for team discovery. Must exceed the underlying ClickHouse
# query's max_execution_time (5 min in CH_LLM_ANALYTICS_SETTINGS) plus retry
# overhead so the activity doesn't get killed before the fallback path runs.
DISCOVERY_ACTIVITY_TIMEOUT = timedelta(minutes=5)
DISCOVERY_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=2)


@dataclasses.dataclass
class TeamDiscoveryInput:
    lookback_days: int = DEFAULT_DISCOVERY_LOOKBACK_DAYS
    sample_percentage: float = DEFAULT_SAMPLE_PERCENTAGE


@temporalio.activity.defn
async def get_team_ids_for_llm_analytics(inputs: TeamDiscoveryInput) -> list[int]:
    """
    Discover teams for LLM analytics workflows.

    Returns guaranteed allowlist teams + a random sample of other teams with AI events.
    On failure, falls back to guaranteed teams only.
    """
    async with Heartbeater():
        config = await asyncio.to_thread(_get_llma_workflow_config)
        guaranteed = set(config.guaranteed_team_ids)

        # FF payload is the source of truth, intentionally overriding
        # TeamDiscoveryInput so config can be tuned from the PostHog UI
        # without a deploy. TeamDiscoveryInput is kept for Temporal's
        # serialization contract but its values are not used at runtime.
        sample_percentage = config.sample_percentage
        lookback_days = config.discovery_lookback_days

        try:
            end = datetime.now(UTC)
            begin = end - timedelta(days=lookback_days)

            from posthog.tasks.llm_analytics_usage_report import get_teams_with_ai_events

            ai_event_teams = await asyncio.to_thread(get_teams_with_ai_events, begin, end)

            remaining = [t for t in ai_event_teams if t not in guaranteed]

            sample_size = math.ceil(len(remaining) * sample_percentage)
            sampled = random.sample(remaining, min(sample_size, len(remaining)))

            result = sorted(guaranteed | set(sampled))

            logger.info(
                "Team discovery completed",
                guaranteed_count=len(guaranteed),
                ai_event_teams_count=len(ai_event_teams),
                remaining_count=len(remaining),
                sampled_count=len(sampled),
                total_count=len(result),
                sample_percentage=sample_percentage,
            )

            return result

        except Exception:
            logger.warning(
                "Team discovery failed, falling back to guaranteed teams",
                exc_info=True,
                guaranteed_count=len(guaranteed),
            )
            return sorted(guaranteed)
