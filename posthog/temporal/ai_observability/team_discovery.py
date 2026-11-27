"""
Team discovery activity for AI observability workflows.

Discovers projects that explicitly enabled clustering and have AI data processing consent.

Config is read from the `llm-analytics-clustering-workflows` feature flag
payload so it can be changed from the PostHog UI without a deploy.
Only the operational skip list applies to discovery. Legacy rollout fields remain
parseable for callers and histories that still carry the old configuration.
"""

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta

from django.db import InterfaceError, OperationalError

import structlog
import posthoganalytics
import temporalio.activity
from temporalio.common import RetryPolicy
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from posthog.sync import database_sync_to_async_pool
from posthog.temporal.ai_observability.coordinator_metrics import increment_consent_query_failed
from posthog.temporal.ai_observability.shared_activities import enabled_clustering_team_ids
from posthog.temporal.common.heartbeat import Heartbeater

from products.ai_observability.backend.facade.evaluation_runtime import consented_team_ids

logger = structlog.get_logger(__name__)

FEATURE_FLAG_KEY = "llm-analytics-clustering-workflows"

# Dev/test default for the legacy `guaranteed_team_ids` payload field. The parser uses
# it when the payload is missing or invalid, which in practice means local development
# or CI, where the posthoganalytics SDK has no flag definitions loaded and returns None.
# Discovery does not read this field, because only projects that enabled clustering run.
DEFAULT_GUARANTEED_TEAM_IDS: list[int] = [
    1,  # Local development
    2,  # Internal PostHog project
]
# Default for the legacy `sample_percentage` payload field. Discovery does not sample
# projects, so this value does not change which projects run.
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
DISCOVERY_FAIL_CLOSED_PATCH_ID = "ai-observability-discovery-fail-closed-2026-09"


@dataclasses.dataclass(frozen=True)
class TeamDiscoveryInput:
    # Restrict opted-in projects to those with data in the coordinator's window.
    window_start: str | None = None
    window_end: str | None = None
    trigger_events: list[str] | None = None


@retry(
    retry=retry_if_exception_type((InterfaceError, OperationalError)),
    stop=stop_after_attempt(3),
    wait=wait_fixed(0.1),
    reraise=True,
)
async def _consented_team_ids_with_retry(team_ids: list[int]) -> set[int]:
    return await database_sync_to_async_pool(consented_team_ids)(team_ids)


@temporalio.activity.defn(name="get_team_ids_for_llm_analytics")
async def get_team_ids_for_ai_observability(inputs: TeamDiscoveryInput | None = None) -> list[int]:
    """
    Discover teams for AI observability workflows.

    Only opted-in projects with AI data processing consent are eligible.
    The operational skip list can pause a project without changing its opt-in.
    """
    async with Heartbeater():
        config = await asyncio.to_thread(_get_ai_observability_workflow_config)
        try:
            enabled = await database_sync_to_async_pool(enabled_clustering_team_ids)()
            discovered = sorted(enabled - set(config.skip_team_ids))
            consented = await _consented_team_ids_with_retry(discovered)
        except Exception:
            # Fail closed: an unreadable consent flag must not let trace content reach a
            # third-party model.
            logger.exception("AI data processing consent filter failed, discovering no teams")
            increment_consent_query_failed()
            return []

        result = [team_id for team_id in discovered if team_id in consented]
        if result:
            from posthog.tasks.ai_observability_usage_report import (
                LLM_ANALYTICS_DISCOVERY_TRIGGER_EVENTS,
                get_teams_with_ai_events,
            )

            end = datetime.fromisoformat(inputs.window_end) if inputs and inputs.window_end else datetime.now(UTC)
            begin = (
                datetime.fromisoformat(inputs.window_start)
                if inputs and inputs.window_start
                else end - timedelta(days=config.discovery_lookback_days)
            )
            active = await asyncio.to_thread(
                get_teams_with_ai_events,
                begin,
                end,
                inputs.trigger_events if inputs and inputs.trigger_events else LLM_ANALYTICS_DISCOVERY_TRIGGER_EVENTS,
                team_ids=result,
            )
            result = sorted(set(result).intersection(active))

        logger.info(
            "Team discovery completed",
            discovered_count=len(discovered),
            total_count=len(result),
        )

        return result
