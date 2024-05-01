from posthog.models import Team
from typing import NamedTuple


class SessionRecordingQueryResult(NamedTuple):
    results: list
    has_more_recording: bool


class SessionRecordingListFromFilters:
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50
    team: Team

    def __init__(
        self,
        team=Team,
        **_,
    ):
        self.team = team

    def run(self) -> SessionRecordingQueryResult:
        return SessionRecordingQueryResult([], False)
