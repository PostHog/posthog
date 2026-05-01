import re
from collections import Counter

import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async, database_sync_to_async_pool
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.search_attributes import POSTHOG_SESSION_RECORDING_ID_KEY
from posthog.temporal.session_replay.summarization_sweep.constants import (
    CH_QUERY_MAX_EXECUTION_SECONDS,
    SCHEDULE_ID_PREFIX,
    SCHEDULE_TYPE,
    STUCK_RASTERIZE_THRESHOLD,
    WORKFLOW_NAME,
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


def _is_team_summarization_allowed(team_id: int) -> bool:
    return SignalSourceConfig.objects.filter(
        team_id=team_id,
        source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
        source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
        enabled=True,
        team__organization__is_ai_data_processing_approved=True,
    ).exists()


def _select_summarization_user(team: Team) -> User | None:
    # Stability matters: the chosen user is embedded in the child's `redis_key_base`.
    config = (
        SignalSourceConfig.objects.filter(
            team_id=team.id,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
        )
        .select_related("created_by")
        .first()
    )
    if config is not None and config.created_by_id is not None:
        return config.created_by
    return team.all_users_with_access().order_by("id").first()


def _load_team_user_and_sessions(team_id: int, lookback_minutes: int) -> tuple[Team, list[str], User | None]:
    team = Team.objects.get(id=team_id)
    session_ids = fetch_recent_session_ids(
        team=team,
        lookback_minutes=lookback_minutes,
        max_execution_time_seconds=CH_QUERY_MAX_EXECUTION_SECONDS,
    )
    if not session_ids:
        return team, [], None
    return team, session_ids, _select_summarization_user(team)


# Session ids land here from ClickHouse and originate at SDK clients. Rejecting anything
# outside this shape keeps untrusted input out of the Temporal visibility query string.
_SAFE_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")


async def _stuck_session_ids(session_ids: list[str]) -> set[str]:
    if not session_ids:
        return set()
    safe_ids = [sid for sid in session_ids if _SAFE_SESSION_ID_RE.match(sid)]
    if len(safe_ids) < len(session_ids):
        logger.warning(
            "summarization_sweep.unsafe_session_id_dropped",
            count=len(session_ids) - len(safe_ids),
        )
    if not safe_ids:
        return set()
    try:
        client = await async_connect()
        ids_clause = ",".join(f'"{sid}"' for sid in safe_ids)
        query = (
            f'WorkflowType = "rasterize-recording" '
            f'AND ExecutionStatus IN ("Failed", "TimedOut") '
            f"AND {POSTHOG_SESSION_RECORDING_ID_KEY.name} IN ({ids_clause})"
        )
        failures: Counter[str] = Counter()
        async for wf in client.list_workflows(query=query):
            for pair in wf.typed_search_attributes:
                if pair.key.name == POSTHOG_SESSION_RECORDING_ID_KEY.name:
                    failures[pair.value] += 1
                    break
        return {sid for sid, n in failures.items() if n >= STUCK_RASTERIZE_THRESHOLD}
    except Exception as exc:
        # Degrade to dispatching normally rather than blocking summarization.
        logger.warning("summarization_sweep.stuck_query_failed", error=str(exc))
        return set()


@activity.defn
async def find_sessions_for_team_activity(inputs: FindSessionsInput) -> FindSessionsResult:
    """Surfaces `team_disabled=True` so the workflow can tear down its own schedule."""
    enabled = await database_sync_to_async(_is_team_summarization_allowed)(inputs.team_id)
    if not enabled:
        return FindSessionsResult(team_id=inputs.team_id, team_disabled=True)

    team, session_ids, system_user = await database_sync_to_async_pool(_load_team_user_and_sessions)(
        inputs.team_id, inputs.lookback_minutes
    )
    if not session_ids:
        return FindSessionsResult(team_id=inputs.team_id)
    if system_user is None:
        logger.warning("No user found to run summarization", team_id=inputs.team_id)
        return FindSessionsResult(team_id=inputs.team_id)

    existing_summaries = await database_sync_to_async_pool(SingleSessionSummary.objects.summaries_exist)(
        team_id=inputs.team_id,
        session_ids=session_ids,
        extra_summary_context=None,
    )
    sessions_to_summarize = [sid for sid in session_ids if not existing_summaries.get(sid)][: inputs.max_sessions]
    stuck = await _stuck_session_ids(sessions_to_summarize)
    sessions_to_summarize = [sid for sid in sessions_to_summarize if sid not in stuck]

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


def _list_allowed_team_ids() -> list[int]:
    return list(
        SignalSourceConfig.objects.filter(
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            enabled=True,
            team__organization__is_ai_data_processing_approved=True,
        ).values_list("team_id", flat=True)
    )


@activity.defn
async def list_enabled_teams_activity() -> list[int]:
    return await database_sync_to_async(_list_allowed_team_ids)()


def _schedule_workflow_type(listing: object) -> str | None:
    try:
        return listing.schedule.action.workflow  # type: ignore[attr-defined]
    except AttributeError:
        return None


@activity.defn
async def list_summarization_schedule_team_ids_activity() -> list[int]:
    from posthog.temporal.common.client import async_connect

    client = await async_connect()
    # The `PostHogScheduleType` attribute is set only by this module's schedules, so
    # one visibility query returns exactly our schedules — no namespace-wide scan.
    query = f'PostHogScheduleType = "{SCHEDULE_TYPE}"'
    prefix = f"{SCHEDULE_ID_PREFIX}-"
    team_ids: list[int] = []
    async for listing in await client.list_schedules(query=query):
        if not listing.id.startswith(prefix):
            continue
        # Belt-and-suspenders: the attribute query should already be exact.
        if _schedule_workflow_type(listing) != WORKFLOW_NAME:
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
