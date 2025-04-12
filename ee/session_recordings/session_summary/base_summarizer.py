from datetime import datetime

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
    def _get_session_metadata(session_id: str, team: Team) -> RecordingMetadata:
        session_metadata = SessionReplayEvents().get_metadata(session_id=str(session_id), team=team)
        if not session_metadata:
            raise ValueError(f"no session metadata found for session_id {session_id}")
        return session_metadata

    @staticmethod
    def _get_session_events(
        session_id: str, session_metadata: RecordingMetadata, team: Team
    ) -> tuple[list[str], list[list[str | datetime]]]:
        session_events_columns, session_events = SessionReplayEvents().get_events(
            session_id=str(session_id),
            team=team,
            metadata=session_metadata,
            events_to_ignore=[
                "$feature_flag_called",
            ],
        )
        if not session_events_columns or not session_events:
            raise ValueError(f"no events found for session_id {session_id}")
        return session_events_columns, session_events
