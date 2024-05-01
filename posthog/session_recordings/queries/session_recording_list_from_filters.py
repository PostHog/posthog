from posthog.models import Team
from typing import NamedTuple


class SessionRecordingQueryResult(NamedTuple):
    results: list
    has_more_recording: bool


class SessionRecordingListFromFilters:
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50

    def __init__(
        self,
        team=Team,
        **kwargs,
    ):
        person_on_events_mode = team.person_on_events_mode
        super().__init__(
            **kwargs,
            team=team,
            person_on_events_mode=person_on_events_mode,
        )

    def run(self) -> SessionRecordingQueryResult:
        return SessionRecordingQueryResult([], False)
