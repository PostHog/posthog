from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.session_recordings.models.session_recording import SessionRecording


class RecordingsHelper:
    def __init__(self, team: Team):
        self.team = team

    def _matching_clickhouse_recordings(
        self,
        session_ids: Iterable[str],
    ) -> set[str]:
        if not session_ids:
            # no need to query if we get invalid input
            return set()

        matches_provided_session_ids = ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["session_id"]),
            right=ast.Array(exprs=[ast.Constant(value=s) for s in session_ids]),
        )

        current_now = datetime.now()

        not_expired = ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq, left=ast.Field(chain=["expiry_time"]), right=ast.Constant(value=current_now)
        )

        query = """
                SELECT
                    session_id,
                    min(min_first_timestamp) as start_time,
                    max(retention_period_days) as retention_period_days,
                    dateTrunc('DAY', start_time) + toIntervalDay(coalesce(retention_period_days, 30)) as expiry_time
                FROM
                    raw_session_replay_events
                WHERE
                    {where_predicates}
                GROUP BY
                    session_id
                HAVING
                    {having_predicates}
                """

        response = execute_hogql_query(
            query,
            placeholders={
                "where_predicates": matches_provided_session_ids,
                "having_predicates": not_expired,
            },
            team=self.team,
        )
        if not response.results:
            return set()

        return {str(result[0]) for result in response.results}

    def _deleted_session_recordings(self, session_ids) -> set[str]:
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
        valid_session_ids = self._matching_clickhouse_recordings(raw_session_ids) - self._deleted_session_recordings(
            raw_session_ids
        )

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
