import json
import dataclasses
from datetime import datetime

import temporalio

from posthog.schema import CachedSessionBatchEventsQueryResponse

from posthog.event_usage import EventSource
from posthog.hogql_queries.ai.session_batch_events_query_runner import (
    SessionBatchEventsQueryRunner,
    create_session_batch_events_query,
)
from posthog.models.team.team import Team
from posthog.redis import get_async_client
from posthog.session_recordings.constants import DEFAULT_TOTAL_EVENTS_PER_QUERY
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async
from posthog.temporal.session_replay.session_summary.state import (
    StateActivitiesEnum,
    generate_state_key,
    store_data_in_redis,
)
from posthog.temporal.session_replay.session_summary_group.types import (
    SessionBatchFetchOutput,
    SessionGroupSummaryInputs,
)

from ee.hogai.session_summaries.constants import MIN_SESSION_DURATION_FOR_SUMMARY_MS
from ee.hogai.session_summaries.session.input_data import add_context_and_filter_events
from ee.hogai.session_summaries.session.summarize_session import (
    SessionSummaryDBData,
    prepare_data_for_single_session_summary,
    prepare_single_session_summary_input,
)
from ee.hogai.session_summaries.utils import logging_session_ids
from ee.models.session_summaries import SingleSessionSummary


def _get_db_events_per_page(
    session_ids: list[str], team: Team, min_timestamp_str: str, max_timestamp_str: str, page_size: int, offset: int
) -> CachedSessionBatchEventsQueryResponse:
    """Fetch events for multiple sessions in a single query and return the response. Separate function to run in a single db_sync_to_async call."""
    query = create_session_batch_events_query(
        session_ids=session_ids,
        after=min_timestamp_str,
        before=max_timestamp_str,
        max_total_events=page_size,
        offset=offset,
    )
    runner = SessionBatchEventsQueryRunner(query=query, team=team)
    response = runner.run(analytics_props={"source": EventSource.POSTHOG_AI})
    if not isinstance(response, CachedSessionBatchEventsQueryResponse):
        msg = (
            f"Failed to fetch events for sessions {logging_session_ids(session_ids)} in team {team.id} "
            f"when fetching batch events for group summary"
        )
        temporalio.activity.logger.error(msg, extra={"team_id": team.id, "signals_type": "session-summaries"})
        raise ValueError(msg)
    return response


def _get_db_columns(response_columns: list) -> list[str]:
    """Get the columns from the response and remove the properties prefix for backwards compatibility."""
    columns = [str(x).replace("properties.", "") for x in response_columns]
    return columns


@temporalio.activity.defn
async def fetch_session_batch_events_activity(
    inputs: SessionGroupSummaryInputs,
) -> SessionBatchFetchOutput:
    """Fetch batch events for multiple sessions using query runner and store per-session data in Redis."""
    fetched_session_ids: list[str] = []
    expected_skip_session_ids: list[str] = []

    redis_client = get_async_client()
    summaries_exist = await database_sync_to_async(
        SingleSessionSummary.objects.summaries_exist, thread_sensitive=False
    )(
        team_id=inputs.team_id,
        session_ids=inputs.session_ids,
        extra_summary_context=inputs.extra_summary_context,
    )
    fetched_session_ids.extend([session_id for session_id, exist in summaries_exist.items() if exist])
    session_ids_to_fetch = [s for s in inputs.session_ids if s not in fetched_session_ids]
    if not session_ids_to_fetch:
        return SessionBatchFetchOutput(
            fetched_session_ids=fetched_session_ids, expected_skip_session_ids=expected_skip_session_ids
        )
    team = await Team.objects.aget(id=inputs.team_id)
    metadata_dict = await database_sync_to_async(SessionReplayEvents().get_group_metadata, thread_sensitive=False)(
        session_ids=session_ids_to_fetch,
        team=team,
        recordings_min_timestamp=datetime.fromisoformat(inputs.min_timestamp_str),
        recordings_max_timestamp=datetime.fromisoformat(inputs.max_timestamp_str),
    )
    filtered_session_ids: list[str] = []
    for session_id in session_ids_to_fetch:
        session_metadata = metadata_dict.get(session_id)
        if not session_metadata:
            temporalio.activity.logger.info(
                f"No metadata found for session {session_id} in team {inputs.team_id}, skipping",
                extra={"session_id": session_id, "team_id": inputs.team_id, "signals_type": "session-summaries"},
            )
            expected_skip_session_ids.append(session_id)
            continue
        duration_ms = (session_metadata["end_time"] - session_metadata["start_time"]).total_seconds() * 1000
        if duration_ms < MIN_SESSION_DURATION_FOR_SUMMARY_MS:
            temporalio.activity.logger.info(
                f"Session {session_id} in team {inputs.team_id} is too short ({duration_ms}ms) to summarize, skipping",
                extra={"session_id": session_id, "team_id": inputs.team_id, "signals_type": "session-summaries"},
            )
            expected_skip_session_ids.append(session_id)
            continue
        filtered_session_ids.append(session_id)
    if not filtered_session_ids:
        return SessionBatchFetchOutput(
            fetched_session_ids=fetched_session_ids, expected_skip_session_ids=expected_skip_session_ids
        )
    # TODO: When increasing the amount of sessions - think about generator-ish approach to avoid OOM
    all_session_events: dict[str, list[tuple]] = {}
    columns, offset, page_size = None, 0, DEFAULT_TOTAL_EVENTS_PER_QUERY
    while True:
        response = await database_sync_to_async(_get_db_events_per_page)(
            session_ids=filtered_session_ids,
            team=team,
            min_timestamp_str=inputs.min_timestamp_str,
            max_timestamp_str=inputs.max_timestamp_str,
            page_size=page_size,
            offset=offset,
        )
        if columns is None:
            columns = _get_db_columns(response.columns)
        if response.session_events:
            for session_item in response.session_events:
                session_id = session_item.session_id
                if session_id not in all_session_events:
                    all_session_events[session_id] = []
                all_session_events[session_id].extend([tuple(event) for event in session_item.events])
        if response.hasMore is not True:
            break
        offset += page_size
    for session_id in filtered_session_ids:
        session_events = all_session_events.get(session_id)
        if not session_events:
            temporalio.activity.logger.info(
                f"No events found for session {session_id} in team {inputs.team_id}, skipping",
                extra={"session_id": session_id, "team_id": inputs.team_id, "signals_type": "session-summaries"},
            )
            expected_skip_session_ids.append(session_id)
            continue
        session_metadata = metadata_dict.get(session_id)
        if not session_metadata:
            temporalio.activity.logger.info(
                f"No metadata found for session {session_id} in team {inputs.team_id} (impossible here), skipping",
                extra={"session_id": session_id, "team_id": inputs.team_id, "signals_type": "session-summaries"},
            )
            expected_skip_session_ids.append(session_id)
            continue
        filtered_columns, filtered_events = add_context_and_filter_events(
            session_events_columns=columns,
            session_events=session_events,
            session_id=session_id,
            session_start_time=session_metadata["start_time"],
            session_end_time=session_metadata["end_time"],
        )
        session_db_data = SessionSummaryDBData(
            session_metadata=session_metadata, session_events_columns=filtered_columns, session_events=filtered_events
        )
        if not session_db_data.session_events or not session_db_data.session_events_columns:
            temporalio.activity.logger.info(
                f"Session {session_id} in team {inputs.team_id} has no events after filtering, skipping",
                extra={"session_id": session_id, "team_id": inputs.team_id, "signals_type": "session-summaries"},
            )
            expected_skip_session_ids.append(session_id)
            continue
        summary_data = await prepare_data_for_single_session_summary(
            session_id=session_id,
            user_id=inputs.user_id,
            session_db_data=session_db_data,
            extra_summary_context=inputs.extra_summary_context,
        )
        input_data = prepare_single_session_summary_input(
            session_id=session_id,
            user_id=inputs.user_id,
            user_distinct_id_to_log=inputs.user_distinct_id_to_log,
            summary_data=summary_data,
            model_to_use=inputs.model_to_use,
            trigger_session_id=inputs.trigger_session_id,
        )
        session_data_key = generate_state_key(
            key_base=inputs.redis_key_base,
            label=StateActivitiesEnum.SESSION_DB_DATA,
            state_id=session_id,
        )
        input_data_str = json.dumps(dataclasses.asdict(input_data))
        fetched_session_ids.append(session_id)
        await store_data_in_redis(
            redis_client=redis_client,
            redis_key=session_data_key,
            data=input_data_str,
            label=StateActivitiesEnum.SESSION_DB_DATA,
        )
    return SessionBatchFetchOutput(
        fetched_session_ids=fetched_session_ids, expected_skip_session_ids=expected_skip_session_ids
    )
