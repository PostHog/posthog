from collections import defaultdict
from datetime import datetime
from collections.abc import Iterable

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.models import Team
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import ttl_days


class RecordingsHelper:
    def __init__(self, team: Team):
        self.team = team
        self._ttl_days = ttl_days(team)

    def session_ids_all(
        self,
        session_ids: Iterable[str],
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> set[str]:
        if not session_ids:
            # no need to query if we get invalid input
            return set()

        # we always want to clamp to TTL
        # technically technically technically we should do what replay listing does and check in postgres too
        # but pinning to TTL is good enough for 90% of cases
        fixed_date_from_or_since_ttl_days = ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["min_first_timestamp"]),
            right=ast.Constant(value=date_from)
            if date_from
            else ast.ArithmeticOperation(
                op=ast.ArithmeticOperationOp.Sub,
                left=ast.Constant(value=date_from),
                right=ast.Call(name="toIntervalDay", args=[ast.Constant(value=self._ttl_days)]),
            ),
        )
        fixed_date_to_or_before_now = ast.CompareOperation(
            op=ast.CompareOperationOp.LtEq,
            left=ast.Field(chain=["max_last_timestamp"]),
            right=ast.Call(name="now", args=[])
            if not date_to or date_to > datetime.now()
            else ast.Constant(value=date_to),
        )
        matching_provided_session_ids = ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["session_id"]),
            right=ast.Array(exprs=[ast.Constant(value=s) for s in session_ids]),
        )

        query = """
          SELECT DISTINCT session_id
          FROM raw_session_replay_events
          WHERE {where_predicates}
          """

        response = execute_hogql_query(
            query,
            placeholders={
                "where_predicates": ast.And(
                    exprs=[
                        fixed_date_from_or_since_ttl_days,
                        fixed_date_to_or_before_now,
                        matching_provided_session_ids,
                    ]
                ),
            },
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
