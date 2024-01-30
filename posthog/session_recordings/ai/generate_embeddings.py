from openai import OpenAI

from posthog.api.activity_log import ServerTimingsGathered
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.utils import get_instance_region
from posthog.models import User, Team


def generate_team_embeddings(team: Team):
    recordings = []  # TODO: figure out how to find unembedded recordings

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
            metadata={"start_time": "TODO: one week ago", "end_time": "TODO: time.now"},
            events_to_ignore=[
                "$feature_flag_called",
            ],
        )
        if not session_events or not session_events[0] or not session_events[1]:
            raise ValueError(f"no events found for session_id {recording.session_id}")

    with timer("generate_input"):
        input = deduplicate_urls(
            collapse_sequence_of_events(
                format_dates(
                    reduce_elements_chain(
                        simplify_window_id(
                            SessionSummaryPromptData(columns=session_events[0], results=session_events[1])
                        )
                    ),
                    start=start_time,
                )
            )
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

    recording.text_embeddings = embeddings
    recording.save()
