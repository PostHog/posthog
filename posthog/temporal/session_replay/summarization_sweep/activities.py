import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async
from posthog.temporal.session_replay.summarization_sweep.constants import (
    CH_QUERY_MAX_EXECUTION_SECONDS,
    SCHEDULE_ID_PREFIX,
)
from posthog.temporal.session_replay.summarization_sweep.models import (
    DeleteTeamScheduleInput,
    FindSessionsInput,
    FindSessionsResult,
    UpsertTeamScheduleInput,
)
from posthog.temporal.session_replay.summarization_sweep.session_candidates import fetch_recent_session_ids

from products.signals.backend.models import SignalSourceConfig

from ee.models.session_summaries import SingleSessionSummary

logger = structlog.get_logger(__name__)


def _is_team_enabled(team_id: int) -> bool:
    return SignalSourceConfig.objects.filter(
        team_id=team_id,
        source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
        source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
        enabled=True,
    ).exists()


def _load_team_user_and_sessions(team_id: int, lookback_minutes: int) -> tuple[Team, list[str], User | None]:
    team = Team.objects.get(id=team_id)
    session_ids = fetch_recent_session_ids(
        team=team,
        lookback_minutes=lookback_minutes,
        max_execution_time_seconds=CH_QUERY_MAX_EXECUTION_SECONDS,
    )
    if not session_ids:
        return team, [], None
    # Stable ordering — the chosen user is embedded in the child's `redis_key_base`.
    system_user = team.all_users_with_access().order_by("id").first()
    return team, session_ids, system_user


@activity.defn
async def find_sessions_for_team_activity(inputs: FindSessionsInput) -> FindSessionsResult:
    """Surfaces `team_disabled=True` so the workflow can tear down its own schedule."""
    enabled = await database_sync_to_async(_is_team_enabled)(inputs.team_id)
    if not enabled:
        return FindSessionsResult(team_id=inputs.team_id, team_disabled=True)

    team, session_ids, system_user = await database_sync_to_async(_load_team_user_and_sessions)(
        inputs.team_id, inputs.lookback_minutes
    )
    if not session_ids:
        return FindSessionsResult(team_id=inputs.team_id)
    if system_user is None:
        logger.warning("No user found to run summarization", team_id=inputs.team_id)
        return FindSessionsResult(team_id=inputs.team_id)

    existing_summaries = await database_sync_to_async(SingleSessionSummary.objects.summaries_exist)(
        team_id=inputs.team_id,
        session_ids=session_ids,
        extra_summary_context=None,
    )
    sessions_to_summarize = [sid for sid in session_ids if not existing_summaries.get(sid)][: inputs.max_sessions]

    return FindSessionsResult(
        team_id=inputs.team_id,
        session_ids=sessions_to_summarize,
        user_id=system_user.id,
        user_distinct_id=system_user.distinct_id,
    )


@activity.defn
async def delete_team_schedule_activity(inputs: DeleteTeamScheduleInput) -> None:
    """Idempotent."""
    if inputs.dry_run:
        logger.info("summarization_sweep.dry_run.delete_team_schedule", team_id=inputs.team_id)
        return

    from posthog.temporal.session_replay.summarization_sweep.schedule import a_delete_team_schedule

    await a_delete_team_schedule(inputs.team_id)


def _list_enabled_team_ids() -> list[int]:
    return list(
        SignalSourceConfig.objects.filter(
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            enabled=True,
        ).values_list("team_id", flat=True)
    )


@activity.defn
async def list_enabled_teams_activity() -> list[int]:
    return await database_sync_to_async(_list_enabled_team_ids)()


@activity.defn
async def list_summarization_schedule_team_ids_activity() -> list[int]:
    from posthog.temporal.common.client import async_connect

    client = await async_connect()
    prefix = f"{SCHEDULE_ID_PREFIX}-"
    team_ids: list[int] = []
    async for listing in await client.list_schedules():
        if not listing.id.startswith(prefix):
            continue
        suffix = listing.id[len(prefix) :]
        try:
            team_ids.append(int(suffix))
        except ValueError:
            logger.warning("summarization_sweep.unparseable_schedule_id", schedule_id=listing.id)
    return team_ids


@activity.defn
async def upsert_team_schedule_activity(inputs: UpsertTeamScheduleInput) -> None:
    if inputs.dry_run:
        logger.info("summarization_sweep.dry_run.upsert_team_schedule", team_id=inputs.team_id)
        return

    from posthog.temporal.session_replay.summarization_sweep.schedule import a_upsert_team_schedule

    await a_upsert_team_schedule(inputs.team_id)
