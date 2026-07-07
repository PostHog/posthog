"""Team discovery for the MCP analytics intent clustering coordinator.

v1 returns a hard-coded ``GUARANTEED_TEAM_IDS`` list — there's no sampling
of teams-with-mcp-events yet. The activity exists so the coordinator's
fan-out shape matches the LLMA precedent and so a future PR can swap in a
ClickHouse sample query without touching the workflow wiring.

Why no sampling in v1:

- MCP analytics is small; the dogfooding cohort is one team.
- The coordinator and worker deployment are themselves new — narrow the
  blast radius until we've validated the daily path on {team 2} for a week.
- Adding sampling later is a constants change, not an architectural one.
"""

import dataclasses
from datetime import timedelta

import structlog
from temporalio import activity
from temporalio.common import RetryPolicy

from posthog.temporal.common.heartbeat import Heartbeater

logger = structlog.get_logger(__name__)


# Teams that always get a daily run regardless of sampling decisions.
# 2 = PostHog Cloud US — the project this repo dogfoods against.
GUARANTEED_TEAM_IDS: list[int] = [2]

# Activity envelope — generous timeout in case we add the ClickHouse sample
# query later. Two retry attempts cover transient cluster blips.
DISCOVERY_ACTIVITY_TIMEOUT = timedelta(minutes=5)
DISCOVERY_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=2)


@dataclasses.dataclass
class TeamDiscoveryInput:
    """Reserved for future use (sample_percentage, lookback_days). Empty in v1."""


@activity.defn
async def get_team_ids_for_mcp_analytics(inputs: TeamDiscoveryInput) -> list[int]:
    """Return the deterministic list of teams to cluster intents for.

    v1: returns ``GUARANTEED_TEAM_IDS`` sorted. A future PR will optionally
    union with a ClickHouse-sampled set of teams that have ``$mcp_tool_call``
    events in the configured window.
    """
    async with Heartbeater():
        team_ids = sorted(GUARANTEED_TEAM_IDS)
        logger.info("mcpa.intent_clustering.team_discovery", count=len(team_ids), team_ids=team_ids)
        return team_ids
