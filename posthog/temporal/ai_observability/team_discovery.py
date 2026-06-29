"""
Team discovery activity for AI observability workflows.

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

# Dev/test floor — only used when the feature flag payload is missing or invalid,
# which in practice means local development or CI, where the posthoganalytics SDK
# has no flag definitions loaded and returns None. The live allowlist of dogfooding
# and customer teams lives in the `llm-analytics-clustering-workflows` flag payload,
# which is the single source of truth; keep this list to bootstrap teams only.
DEFAULT_GUARANTEED_TEAM_IDS: list[int] = [
    1,  # Local development
    2,  # Internal PostHog project
]
# Default sample percentage for gradual rollout.
# 0.0 = only guaranteed teams, 0.5 = 50% of remaining, 1.0 = all teams with AI events.
DEFAULT_SAMPLE_PERCENTAGE: float = 0.5
DEFAULT_DISCOVERY_LOOKBACK_DAYS: int = 7

# Used by coordinators only in the last-resort fallback path (when the discovery
# activity itself fails), so pointing at the dev/test default is fine.
GUARANTEED_TEAM_IDS = DEFAULT_GUARANTEED_TEAM_IDS


@dataclasses.dataclass
class AIObservabilityWorkflowConfig:
    guaranteed_team_ids: list[int]
    skip_team_ids: list[int]
    sample_percentage: float
    discovery_lookback_days: int


def _get_ai_observability_workflow_config() -> AIObservabilityWorkflowConfig:
    """Read AI observability team-discovery config from the feature flag payload, falling back to defaults."""
    try:
        payload: dict | None = posthoganalytics.get_feature_flag_payload(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
            FEATURE_FLAG_KEY, "internal_llma_team_discovery"
        )

        if not isinstance(payload, dict):
            logger.info("No valid FF payload, using defaults", payload_type=type(payload).__name__)
            return AIObservabilityWorkflowConfig(
                guaranteed_team_ids=DEFAULT_GUARANTEED_TEAM_IDS,
                skip_team_ids=[],
                sample_percentage=DEFAULT_SAMPLE_PERCENTAGE,
                discovery_lookback_days=DEFAULT_DISCOVERY_LOOKBACK_DAYS,
            )

        guaranteed = payload.get("guaranteed_team_ids", DEFAULT_GUARANTEED_TEAM_IDS)
        if not isinstance(guaranteed, list) or not all(isinstance(t, int) for t in guaranteed):
            guaranteed = DEFAULT_GUARANTEED_TEAM_IDS

        skip = payload.get("skip_team_ids", [])
        if not isinstance(skip, list) or not all(isinstance(t, int) for t in skip):
            skip = []

        sample_pct = payload.get("sample_percentage", DEFAULT_SAMPLE_PERCENTAGE)
        if not isinstance(sample_pct, (int, float)) or not (0.0 <= float(sample_pct) <= 1.0):
            sample_pct = DEFAULT_SAMPLE_PERCENTAGE

        lookback_days = payload.get("discovery_lookback_days", DEFAULT_DISCOVERY_LOOKBACK_DAYS)
        if not isinstance(lookback_days, int) or isinstance(lookback_days, bool) or lookback_days <= 0:
            lookback_days = DEFAULT_DISCOVERY_LOOKBACK_DAYS

        logger.info(
            "Loaded AI observability config from feature flag",
            guaranteed_count=len(guaranteed),
            skip_count=len(skip),
            sample_percentage=sample_pct,
            discovery_lookback_days=lookback_days,
        )

        return AIObservabilityWorkflowConfig(
            guaranteed_team_ids=guaranteed,
            skip_team_ids=skip,
            sample_percentage=float(sample_pct),
            discovery_lookback_days=lookback_days,
        )
    except Exception:
        logger.warning("Failed to read AI observability config from feature flag, using defaults", exc_info=True)
        return AIObservabilityWorkflowConfig(
            guaranteed_team_ids=DEFAULT_GUARANTEED_TEAM_IDS,
            skip_team_ids=[],
            sample_percentage=DEFAULT_SAMPLE_PERCENTAGE,
            discovery_lookback_days=DEFAULT_DISCOVERY_LOOKBACK_DAYS,
        )


def get_min_traces_override(team_id: int) -> int | None:
    """Per-team override for the clustering minimum-item threshold, from the flag payload.

    Lets low-volume teams (e.g. staging projects) opt into clustering below the global
    minimum. Returns None when the team has no override, so callers keep the default.
    """
    try:
        payload: dict | None = posthoganalytics.get_feature_flag_payload(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
            FEATURE_FLAG_KEY, "internal_llma_team_discovery"
        )
        if not isinstance(payload, dict):
            return None
        overrides = payload.get("min_traces_overrides", {})
        if not isinstance(overrides, dict):
            return None
        override = overrides.get(str(team_id))
        if not isinstance(override, int) or isinstance(override, bool) or override <= 0:
            return None
        return override
    except Exception:
        logger.warning("Failed to read min_traces override from feature flag", exc_info=True)
        return None


# Activity timeout for team discovery. Must exceed the underlying ClickHouse
# query's max_execution_time (5 min in CH_AI_OBSERVABILITY_SETTINGS) plus retry
# overhead so the activity doesn't get killed before the fallback path runs.
DISCOVERY_ACTIVITY_TIMEOUT = timedelta(minutes=5)
DISCOVERY_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=2)


@dataclasses.dataclass
class TeamDiscoveryInput:
    # Empty: discovery config is read from the flag payload inside the activity.
    pass


# TODO: drop `inputs`/TeamDiscoveryInput next release; kept so pre-rollout activity tasks still deserialize.
@temporalio.activity.defn(name="get_team_ids_for_llm_analytics")
async def get_team_ids_for_ai_observability(inputs: TeamDiscoveryInput | None = None) -> list[int]:
    """
    Discover teams for AI observability workflows.

    Config (guaranteed/skip/sample/lookback) is read from the feature flag payload.
    Returns guaranteed allowlist teams + a random sample of other teams with AI events.
    On failure, falls back to guaranteed teams only.
    """
    async with Heartbeater():
        config = await asyncio.to_thread(_get_ai_observability_workflow_config)
        guaranteed = set(config.guaranteed_team_ids)
        skip = set(config.skip_team_ids)

        sample_percentage = config.sample_percentage
        lookback_days = config.discovery_lookback_days

        try:
            end = datetime.now(UTC)
            begin = end - timedelta(days=lookback_days)

            from posthog.tasks.ai_observability_usage_report import (
                LLM_ANALYTICS_DISCOVERY_TRIGGER_EVENTS,
                get_teams_with_ai_events,
            )

            ai_event_teams = await asyncio.to_thread(
                get_teams_with_ai_events,
                begin,
                end,
                LLM_ANALYTICS_DISCOVERY_TRIGGER_EVENTS,
            )

            remaining = [t for t in ai_event_teams if t not in guaranteed and t not in skip]

            sample_size = math.ceil(len(remaining) * sample_percentage)
            sampled = random.sample(remaining, min(sample_size, len(remaining)))

            # Guaranteed teams first: the coordinator processes teams in this order and
            # may exhaust its run budget before reaching the tail, so allowlisted teams
            # must never sit behind the sampled set.
            result = sorted(guaranteed - skip) + sorted(sampled)

            logger.info(
                "Team discovery completed",
                guaranteed_count=len(guaranteed),
                skip_count=len(skip),
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
                skip_count=len(skip),
            )
            return sorted(guaranteed - skip)
