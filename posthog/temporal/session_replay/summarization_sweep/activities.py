import json
import hashlib
from collections.abc import Mapping
from typing import Any

import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.models.user import User
from posthog.redis import get_async_client
from posthog.sync import database_sync_to_async, database_sync_to_async_pool
from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_FINGERPRINT_KEY
from posthog.temporal.session_replay.rasterize_recording.activities.stuck_counter import read_stuck_session_ids
from posthog.temporal.session_replay.summarization_sweep.constants import (
    CH_QUERY_MAX_EXECUTION_SECONDS,
    EVENTS_PREFILTER_QUERY_MAX_EXECUTION_SECONDS,
    SCHEDULE_ID_PREFIX,
    SCHEDULE_TYPE,
    STUCK_RASTERIZE_THRESHOLD,
    WORKFLOW_NAME,
)
from posthog.temporal.session_replay.summarization_sweep.session_candidates import (
    coerce_sample_rate,
    fetch_recent_session_ids,
    filter_session_ids_with_events,
)
from posthog.temporal.session_replay.summarization_sweep.types import (
    DeleteTeamScheduleInput,
    FindSessionsInput,
    FindSessionsResult,
    UpsertTeamScheduleInput,
)

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


def _select_summarization_user(team: Team, config: SignalSourceConfig | None) -> User | None:
    # Stability matters: the chosen user is embedded in the child's `redis_key_base`.
    if config is not None and config.created_by_id is not None:
        return config.created_by
    return team.all_users_with_access().order_by("id").first()


def _load_team_user_and_sessions(team_id: int, lookback_minutes: int) -> tuple[Team, list[str], User | None]:
    team = Team.objects.get(id=team_id)
    config = (
        SignalSourceConfig.objects.filter(
            team_id=team_id,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            enabled=True,
        )
        .select_related("created_by")
        .first()
    )
    # Race: was enabled at `_is_team_summarization_allowed`, now disabled. No-op cycle.
    if config is None:
        return team, [], None
    raw_filters = config.config.get("recording_filters")
    session_ids = fetch_recent_session_ids(
        team=team,
        lookback_minutes=lookback_minutes,
        sample_rate=coerce_sample_rate(config.config.get("sample_rate")),
        recording_filters=raw_filters if isinstance(raw_filters, dict) else None,
        max_execution_time_seconds=CH_QUERY_MAX_EXECUTION_SECONDS,
    )
    if not session_ids:
        return team, [], None
    return team, session_ids, _select_summarization_user(team, config)


async def _stuck_session_ids(team_id: int, session_ids: list[str]) -> set[str]:
    if not session_ids:
        return set()
    try:
        return await read_stuck_session_ids(
            redis_client=get_async_client(),
            team_id=team_id,
            session_ids=session_ids,
            threshold=STUCK_RASTERIZE_THRESHOLD,
        )
    except Exception as exc:
        # Degrade to dispatching normally rather than blocking summarization.
        logger.warning("summarization_sweep.stuck_lookup_failed", error=str(exc))
        return set()


@activity.defn
async def find_sessions_for_team_activity(inputs: FindSessionsInput) -> FindSessionsResult:
    # No-op when disabled; the reconciler will tear down the schedule on its next tick.
    enabled = await database_sync_to_async(_is_team_summarization_allowed)(inputs.team_id)
    if not enabled:
        return FindSessionsResult(team_id=inputs.team_id)

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
    sessions_to_summarize = [sid for sid in session_ids if not existing_summaries.get(sid)]
    # Recording-only sessions never write a summary row, so summaries_exist can't dedup them.
    if sessions_to_summarize:
        sessions_with_events = await database_sync_to_async_pool(filter_session_ids_with_events)(
            team=team,
            session_ids=sessions_to_summarize,
            lookback_minutes=inputs.lookback_minutes,
            max_execution_time_seconds=EVENTS_PREFILTER_QUERY_MAX_EXECUTION_SECONDS,
        )
        sessions_to_summarize = [sid for sid in sessions_to_summarize if sid in sessions_with_events]
    stuck = await _stuck_session_ids(inputs.team_id, sessions_to_summarize)
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
    from posthog.temporal.session_replay.summarization_sweep.schedule import a_delete_team_schedule

    await a_delete_team_schedule(inputs.team_id)


def compute_schedule_fingerprint(config: Mapping[str, Any] | None) -> str:
    """Stable hash of the SignalSourceConfig dict — used to detect drift after UI edits."""
    canonical = json.dumps(config or {}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _list_allowed_team_fingerprints() -> dict[int, str]:
    rows = SignalSourceConfig.objects.filter(
        source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
        source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
        enabled=True,
        team__organization__is_ai_data_processing_approved=True,
    ).values_list("team_id", "config")
    return {team_id: compute_schedule_fingerprint(config) for team_id, config in rows}


@activity.defn
async def list_enabled_teams_activity() -> dict[int, str]:
    return await database_sync_to_async(_list_allowed_team_fingerprints)()


def _load_team_config(team_id: int) -> Mapping[str, Any] | None:
    cfg = (
        SignalSourceConfig.objects.filter(
            team_id=team_id,
            source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
            source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
            enabled=True,
        )
        .values_list("config", flat=True)
        .first()
    )
    return cfg


def _schedule_workflow_type(listing: object) -> str | None:
    try:
        return listing.schedule.action.workflow  # type: ignore[attr-defined]
    except AttributeError:
        return None


def _schedule_fingerprint(listing: object) -> str | None:
    try:
        attrs = listing.typed_search_attributes  # type: ignore[attr-defined]
    except AttributeError:
        return None
    for pair in attrs:
        if pair.key.name == POSTHOG_SCHEDULE_FINGERPRINT_KEY.name:
            return pair.value
    return None


@activity.defn
async def list_summarization_schedule_team_ids_activity() -> dict[int, str | None]:
    """{team_id: stored_fingerprint} for existing schedules; None for untagged legacy ones."""
    from posthog.temporal.common.client import async_connect

    client = await async_connect()
    query = f'PostHogScheduleType = "{SCHEDULE_TYPE}"'
    prefix = f"{SCHEDULE_ID_PREFIX}-"
    out: dict[int, str | None] = {}
    async for listing in await client.list_schedules(query=query):
        if not listing.id.startswith(prefix):
            continue
        if _schedule_workflow_type(listing) != WORKFLOW_NAME:
            continue
        suffix = listing.id[len(prefix) :]
        try:
            team_id = int(suffix)
        except ValueError:
            logger.warning("summarization_sweep.unparseable_schedule_id", schedule_id=listing.id)
            continue
        out[team_id] = _schedule_fingerprint(listing)
    return out


@activity.defn
async def upsert_team_schedule_activity(inputs: UpsertTeamScheduleInput) -> None:
    from posthog.temporal.session_replay.summarization_sweep.schedule import a_upsert_team_schedule

    await a_upsert_team_schedule(inputs.team_id)
