from openai import OpenAI

from typing import Dict

from posthog.api.activity_log import ServerTimingsGathered
from posthog.utils import get_instance_region
from posthog.models import User, Team

from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.session_recordings.ai.utils import (
    SessionSummaryPromptData,
    reduce_elements_chain,
    collapse_sequence_of_events,
)

from posthog.clickhouse.client import sync_execute

BATCH_FLUSH_SIZE = 10


def generate_team_embeddings(team: Team):
    recordings = fetch_recordings(team=team)

    while len(recordings) > 0:
        batched_embeddings = []
        for recording in recordings:
            embeddings = generate_recording_embeddings(recording=recording)
            batched_embeddings.append(
                {
                    "session_id": recording.id,
                    "team_id": team.pk,
                    "embeddings": embeddings,
                    "generation_timestamp": "now()",
                }
            )

        flush_embeddings_to_clickhouse(embeddings=batched_embeddings)

        recordings = fetch_recordings(team=team)


def fetch_recordings(team: Team):
    query = """
            SELECT
                *
            FROM
                session_replay_embeddings
            PREWHERE
                team_id = %(team_id)s
                AND empty(embeddings)
            LIMIT %(batch_flush_size)s
        """

    return sync_execute(
        query,
        {"team_id": team.pk, "batch_flush_size": BATCH_FLUSH_SIZE},
    )


def flush_embeddings_to_clickhouse(embeddings):
    sync_execute("INSERT INTO session_replay_embeddings (*) VALUES", embeddings)


def generate_recording_embeddings(recording: SessionRecording, user: User):
    timer = ServerTimingsGathered()
    client = OpenAI()

    instance_region = get_instance_region() or "HOBBY"

    with timer("get_events"):
        session_events = SessionReplayEvents().get_events(
            session_id=str(recording.session_id),
            team=recording.team,
            metadata={"start_time": "now() - interval 7 days", "end_time": "now()"},
            events_to_ignore=[
                "$feature_flag_called",
            ],
        )
        if not session_events or not session_events[0] or not session_events[1]:
            raise ValueError(f"no events found for session_id {recording.session_id}")

    with timer("generate_input"):
        processed_sessions = collapse_sequence_of_events(
            reduce_elements_chain(SessionSummaryPromptData(columns=session_events[0], results=session_events[1]))
        )

    with timer("prepare_input"):
        input = "\n".join(
            compact_result(
                event_name=result[processed_sessions.column_index("event")],
                event_count=result[processed_sessions.column_index("event_repetition_count")],
                elements_chain=result[processed_sessions.column_index("elements_chain")],
            )
            for result in processed_sessions.results
        )

    with timer("openai_completion"):
        embeddings = (
            client.embeddings.create(
                input=input,
                model="text-embedding-3-small",
                user=f"{instance_region}/{user.pk}",
            )
            .data[0]
            .embedding
        )

    return embeddings


def compact_result(event_name: str, event_count: int, elements_chain: Dict[str, str]):
    return event_name + " " + event_count + " " + ",".join(elements_chain.values)
