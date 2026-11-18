import dataclasses
from datetime import UTC, datetime

import structlog
from temporalio import activity

from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.mcp_analytics.backend.constants import MCP_TOOL_CALL_EVENT
from products.mcp_analytics.backend.wrapped.generate import generate_wrapped_snapshot

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class WrappedDiscoveryInputs:
    year: int


@dataclasses.dataclass(frozen=True)
class WrappedTeamInputs:
    team_id: int
    year: int


def wrapped_team_ids(year: int) -> list[int]:
    """Projects that sent a tool call this year, read from event definitions so no team's events are scanned.

    Each project still has to clear the eligibility bar when its snapshot is generated.
    """
    team_ids = (
        EventDefinition.objects.filter(name=MCP_TOOL_CALL_EVENT, last_seen_at__gte=datetime(year, 1, 1, tzinfo=UTC))
        .values_list("team_id", flat=True)
        .distinct()
    )
    return sorted(team_ids)


@activity.defn
async def discover_wrapped_team_ids_activity(inputs: WrappedDiscoveryInputs) -> list[int]:
    async with Heartbeater():
        return await database_sync_to_async(wrapped_team_ids)(inputs.year)


def _generate(team_id: int, year: int) -> str:
    with team_scope(team_id):
        team = Team.objects.get(id=team_id)
        return generate_wrapped_snapshot(team, year).status


@activity.defn
async def generate_wrapped_activity(inputs: WrappedTeamInputs) -> str:
    async with Heartbeater():
        status = await database_sync_to_async(_generate)(inputs.team_id, inputs.year)
    logger.info("mcpa.wrapped.team_generated", team_id=inputs.team_id, year=inputs.year, status=status)
    return status
