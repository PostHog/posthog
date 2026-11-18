import dataclasses
from datetime import UTC, datetime

import structlog
import posthoganalytics
from temporalio import activity

from posthog.models.scoping import team_scope
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.mcp_analytics.wrapped.constants import COMPUTE_FEATURE_FLAG

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


def _compute_enabled(team: Team) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                COMPUTE_FEATURE_FLAG,
                f"internal_mcpa_wrapped_{team.id}",
                groups={"organization": str(team.organization_id), "project": str(team.uuid)},
                send_feature_flag_events=False,
            )
        )
    except Exception:
        # A failed check skips the project. The run never computes one the flag was meant to leave out.
        logger.warning("mcpa.wrapped.flag_check_failed", team_id=team.id, exc_info=True)
        return False


def wrapped_team_ids(year: int) -> list[int]:
    """Projects that sent a tool call this year and have the compute flag on."""
    candidate_ids = (
        EventDefinition.objects.filter(name=MCP_TOOL_CALL_EVENT, last_seen_at__gte=datetime(year, 1, 1, tzinfo=UTC))
        .values_list("team_id", flat=True)
        .distinct()
    )
    teams = Team.objects.filter(id__in=list(candidate_ids)).only("id", "uuid", "organization_id")
    return sorted(team.id for team in teams if _compute_enabled(team))


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
