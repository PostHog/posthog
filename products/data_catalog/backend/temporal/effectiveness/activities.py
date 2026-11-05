from temporalio import activity

from posthog.models import Team
from posthog.sync import database_sync_to_async

from ...facade.enums import EFFECTIVENESS_FLAG_KEY
from ...logic.effectiveness import TeamSkipped, capture_effectiveness, capture_team_skipped, measure_team
from ...logic.usage_scan import teams_with_metrics_and_flag
from .types import MeasureTeamInput, TeamMeasured


@activity.defn(name="data-catalog-effectiveness-list-teams")
async def list_effectiveness_teams() -> list[int]:
    return await database_sync_to_async(teams_with_metrics_and_flag, thread_sensitive=False)(EFFECTIVENESS_FLAG_KEY)


@activity.defn(name="data-catalog-effectiveness-measure-team")
async def measure_effectiveness(input: MeasureTeamInput) -> TeamMeasured:
    result = await measure_team(
        team_id=input.team_id,
        telemetry_team_id=input.telemetry_team_id,
        window_start=input.window_start,
        window_end=input.window_end,
        heartbeat=activity.heartbeat,
    )
    team = await database_sync_to_async(Team.objects.get, thread_sensitive=False)(id=input.team_id)
    if isinstance(result, TeamSkipped):
        await database_sync_to_async(capture_team_skipped, thread_sensitive=False)(
            result, team, window_start=input.window_start, window_end=input.window_end
        )
        return TeamMeasured(skipped=True)

    await database_sync_to_async(capture_effectiveness, thread_sensitive=False)(result, team)
    return TeamMeasured(skipped=False, analysis_sessions=result.analysis_sessions, rows=len(result.rows))
