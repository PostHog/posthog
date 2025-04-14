from datetime import datetime

from ee.session_recordings.session_summary.utils import (
    load_session_metadata_from_json,
    load_session_recording_events_from_csv,
)
from posthog.session_recordings.models.metadata import RecordingMetadata
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.models import User, Team
from posthog.session_recordings.models.session_recording import SessionRecording


class BaseReplaySummarizer:
    def __init__(self, recording: SessionRecording, user: User, team: Team):
        self.recording = recording
        self.user = user
        self.team = team

    @staticmethod
    def _get_session_metadata(session_id: str, team: Team, local_path: str | None = None) -> RecordingMetadata:
        if not local_path:
            session_metadata = SessionReplayEvents().get_metadata(session_id=str(session_id), team=team)
        else:
            session_metadata = load_session_metadata_from_json(local_path)
        if not session_metadata:
            raise ValueError(f"no session metadata found for session_id {session_id}")
        return session_metadata

    @staticmethod
    def _get_session_events(
        session_id: str, session_metadata: RecordingMetadata, team: Team, local_path: str | None = None
    ) -> tuple[list[str], list[list[str | datetime]]]:
        if not local_path:
            session_events_columns, session_events = SessionReplayEvents().get_events(
                session_id=str(session_id),
                team=team,
                metadata=session_metadata,
                events_to_ignore=[
                    "$feature_flag_called",
                ],
            )
        else:
            session_events_columns, session_events = load_session_recording_events_from_csv(local_path)
        if not session_events_columns or not session_events:
            raise ValueError(f"no events found for session_id {session_id}")
        return session_events_columns, session_events
