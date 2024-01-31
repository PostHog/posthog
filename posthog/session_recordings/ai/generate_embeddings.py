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


def generate_team_embeddings(team: Team):
    recordings = []  # TODO: Query for unembedded recordings

    for recording in recordings:
        update_embedding(recording=recording)


def update_embedding(recording: SessionRecording, user: User):
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
        _ = (
            client.embeddings.create(
                input=input,
                model="text-embedding-3-small",
                user=f"{instance_region}/{user.pk}",
            )
            .data[0]
            .embedding
        )

    # TODO: push embeddings to Kafka topic / ClickHouse


def compact_result(event_name: str, event_count: int, elements_chain: Dict[str, str]):
    return event_name + " " + event_count + " " + ",".join(elements_chain.values)
