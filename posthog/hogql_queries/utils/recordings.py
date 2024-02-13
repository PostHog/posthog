from collections import defaultdict

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.models import Team
from posthog.session_recordings.models.session_recording import SessionRecording


class RecordingsHelper:
    def __init__(self, team: Team):
        self.team = team

    def session_ids_all(self, session_ids) -> set[str]:
        query = """
          SELECT DISTINCT session_id
          FROM session_replay_events
          WHERE session_id in {session_ids}
          """

        # TODO: Date filters, are they needed?

        response = execute_hogql_query(
            query,
            placeholders={"session_ids": ast.Array(exprs=[ast.Constant(value=s) for s in session_ids])},
            team=self.team,
        )
        if not response.results:
            return set()

        return {str(result[0]) for result in response.results}

    def session_ids_deleted(self, session_ids) -> set[str]:
        return set(
            SessionRecording.objects.filter(team_id=self.team.pk, session_id__in=session_ids, deleted=True).values_list(
                "session_id", flat=True
            )
        )

    def get_recordings(self, matching_events) -> dict[str, list[dict]]:
        mapped_events = defaultdict(list)
        for event in matching_events:
            mapped_events[event[2]].append(event)

        raw_session_ids = mapped_events.keys()
        valid_session_ids = self.session_ids_all(raw_session_ids) - self.session_ids_deleted(raw_session_ids)

        return {
            str(session_id): [
                {
                    "timestamp": event[0],
                    "uuid": event[1],
                    "window_id": event[3],
                }
                for event in events
            ]
            for session_id, events in mapped_events.items()
            if session_id in valid_session_ids and len(events) > 0
        }
