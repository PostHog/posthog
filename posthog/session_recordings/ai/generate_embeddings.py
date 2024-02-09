from openai import OpenAI

from typing import Dict

from prometheus_client import Histogram

from posthog.models import Team

from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.ai.utils import (
    SessionSummaryPromptData,
    reduce_elements_chain,
    simplify_window_id,
    format_dates,
    collapse_sequence_of_events,
)

from posthog.clickhouse.client import sync_execute
import datetime
import pytz

GENERATE_RECORDING_EMBEDDING_TIMING = Histogram(
    "posthog_session_recordings_generate_recording_embedding",
    "Time spent generating recording embeddings for a single session",
)

BATCH_FLUSH_SIZE = 10


def generate_team_embeddings(team: Team):
    recordings = fetch_recordings(team=team)

    while len(recordings) > 0:
        batched_embeddings = []
        for recording in recordings:
            session_id = recording[0]

            with GENERATE_RECORDING_EMBEDDING_TIMING.time():
                embeddings = generate_recording_embeddings(session_id=session_id, team=team)

            batched_embeddings.append(
                {
                    "session_id": session_id,
                    "team_id": team.pk,
                    "embeddings": embeddings,
                }
            )
        flush_embeddings_to_clickhouse(embeddings=batched_embeddings)
        recordings = fetch_recordings(team=team)


def fetch_recordings(team: Team):
    query = """
            WITH embedding_ids AS
            (
                SELECT
                    session_id
                from
                    session_replay_embeddings
                where
                    team_id = %(team_id)s
            )
            SELECT DISTINCT
                session_id
            FROM
                session_replay_events
            WHERE
                session_id NOT IN embedding_ids
                AND team_id = %(team_id)s
            LIMIT %(batch_flush_size)s
        """

    return sync_execute(
        query,
        {"team_id": team.pk, "batch_flush_size": BATCH_FLUSH_SIZE},
    )


def flush_embeddings_to_clickhouse(embeddings):
    sync_execute("INSERT INTO session_replay_embeddings (session_id, team_id, embeddings) VALUES", embeddings)


def generate_recording_embeddings(session_id: str, team: Team):
    client = OpenAI()

    session_metadata = SessionReplayEvents().get_metadata(session_id=str(session_id), team=team)
    if not session_metadata:
        raise ValueError(f"no session metadata found for session_id {session_id}")

    session_events = SessionReplayEvents().get_events(
        session_id=str(session_id),
        team=team,
        metadata=session_metadata,
        events_to_ignore=[
            "$feature_flag_called",
        ],
    )
    if not session_events or not session_events[0] or not session_events[1]:
        raise ValueError(f"no events found for session_id {session_id}")

    processed_sessions = collapse_sequence_of_events(
        format_dates(
            reduce_elements_chain(
                simplify_window_id(SessionSummaryPromptData(columns=session_events[0], results=session_events[1]))
            ),
            start=datetime.datetime(1970, 1, 1, tzinfo=pytz.UTC),  # epoch timestamp
        )
    )

    processed_sessions_index = processed_sessions.column_index("event")
    current_url_index = processed_sessions.column_index("$current_url")
    elements_chain_index = processed_sessions.column_index("elements_chain")

    input = (
        str(session_metadata)
        + "\n"
        + "\n".join(
            compact_result(
                event_name=result[processed_sessions_index] if processed_sessions_index is not None else "",
                current_url=result[current_url_index] if current_url_index is not None else "",
                elements_chain=result[elements_chain_index] if elements_chain_index is not None else "",
            )
            for result in processed_sessions.results
        )
    )

    embeddings = (
        client.embeddings.create(
            input=input,
            model="text-embedding-3-small",
        )
        .data[0]
        .embedding
    )

    return embeddings


def compact_result(event_name: str, current_url: int, elements_chain: Dict[str, str] | str) -> str:
    elements_string = elements_chain if isinstance(elements_chain, str) else ", ".join(str(e) for e in elements_chain)
    return f"{event_name} {current_url} {elements_string}"
