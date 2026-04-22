from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team


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

        not_deleted = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Call(name="max", args=[ast.Field(chain=["is_deleted"])]),
            right=ast.Constant(value=0),
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

        tag_queries(team_id=self.team.id, product=Product.REPLAY, feature=Feature.QUERY)
        response = execute_hogql_query(
            query,
            placeholders={
                "where_predicates": matches_provided_session_ids,
                "having_predicates": ast.And(exprs=[not_expired, not_deleted]),
            },
            team=self.team,
        )
        if not response.results:
            return set()

        return {str(result[0]) for result in response.results}

    def get_recordings(self, matching_events) -> dict[str, list[dict]]:
        mapped_events = defaultdict(list)
        for event in matching_events:
            mapped_events[event[2]].append(event)

        raw_session_ids = mapped_events.keys()
        valid_session_ids = self._matching_clickhouse_recordings(raw_session_ids)

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
