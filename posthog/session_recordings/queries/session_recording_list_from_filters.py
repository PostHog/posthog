from posthog.models import Team
from typing import NamedTuple
from posthog.hogql.query import execute_hogql_query


class SessionRecordingQueryResult(NamedTuple):
    results: list
    has_more_recording: bool


class SessionRecordingListFromFilters:
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50

    SAMPLE_QUERY: str = """
        SELECT s.session_id
        FROM raw_session_replay_events s
        LIMIT 10
        """

    def __init__(
        self,
        team=Team,
        **kwargs,
    ):
        super().__init__(
            **kwargs,
            team=team,
        )

    def run(self) -> SessionRecordingQueryResult:
        query_results = execute_hogql_query(
            query=self.SAMPLE_QUERY,
            team=self.team,
        )

        return SessionRecordingQueryResult(query_results, False)
