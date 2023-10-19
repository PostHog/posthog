from collections import defaultdict
from datetime import timedelta
import json
from typing import DefaultDict, Dict, List, Optional, Any, cast
from posthog.api.element import ElementSerializer


from posthog.clickhouse.client.connection import Workload
from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.models import Team
from posthog.models.element.element import chain_to_elements
from posthog.schema import EventType, SessionsTimelineQuery, SessionsTimelineQueryResponse, TimelineEntry


class SessionsTimelineQueryRunner(QueryRunner):
    query: SessionsTimelineQuery
    query_type = SessionsTimelineQuery

    def __init__(
        self,
        query: SessionsTimelineQuery | Dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
    ):
        super().__init__(query, team, timings)
        if isinstance(query, SessionsTimelineQuery):
            self.query = query
        else:
            self.query = SessionsTimelineQuery.model_validate(query)

    def to_query(self) -> ast.SelectQuery:
        if self.timings is None:
            self.timings = HogQLTimings()

        with self.timings.measure("build_ast"):
            select_query = cast(
                ast.SelectQuery,
                parse_select(
                    """
                    WITH (
                        SELECT DISTINCT $session_id
                        FROM events
                        WHERE events.timestamp > toDateTime({after}) AND events.timestamp <= toDateTime({before})
                        LIMIT 100
                    ) AS relevant_session_ids
                    SELECT uuid, $session_id, timestamp, event, properties, distinct_id, elements_chain
                    FROM events
                    WHERE
                        events.timestamp >= (
                            SELECT min(timestamp)
                            FROM events
                            WHERE events.$session_id IN relevant_session_ids OR (
                                $session_id IS NULL
                                AND events.timestamp > toDateTime({after}) AND events.timestamp < toDateTime({before})
                            )
                        )
                        AND events.timestamp <= (
                            SELECT max(timestamp)
                            FROM events
                            WHERE events.$session_id IN relevant_session_ids OR (
                                $session_id IS NULL
                                AND events.timestamp > toDateTime({after}) AND events.timestamp < toDateTime({before})
                            )
                        )
                    ORDER BY timestamp ASC""",
                    placeholders={
                        "before": ast.Constant(value=self.query.before),
                        "after": ast.Constant(value=self.query.after),
                    },
                ),
            )
            assert select_query.ctes is not None
            assert isinstance(select_query.ctes["relevant_session_ids"].expr, ast.SelectQuery)
            if self.query.personId:
                select_query.ctes["relevant_session_ids"].expr.where = ast.CompareOperation(
                    left=ast.Field(chain=["person_id"]),
                    right=ast.Constant(value=self.query.personId),
                    op=ast.CompareOperationOp.Eq,
                )
                select_query.where = ast.CompareOperation(
                    left=ast.Field(chain=["person_id"]),
                    right=ast.Constant(value=self.query.personId),
                    op=ast.CompareOperationOp.Eq,
                )
            return select_query

    def calculate(self) -> SessionsTimelineQueryResponse:
        query_result = execute_hogql_query(
            query=self.to_query(),
            team=self.team,
            workload=Workload.ONLINE,
            query_type="SessionsTimelineQuery",
            timings=self.timings,
        )
        assert query_result.results is not None
        timeline_entries_map: DefaultDict[str, List[EventType]] = defaultdict(list)
        for (
            uuid,
            session_id,
            timestamp_parsed,
            event,
            properties_raw,
            distinct_id,
            elements_chain,
        ) in query_result.results:
            timeline_entries_map[session_id].append(
                EventType(
                    id=str(uuid),
                    distinct_id=distinct_id,
                    event=event,
                    timestamp=timestamp_parsed.isoformat(),
                    properties=json.loads(properties_raw),
                    elements=ElementSerializer(chain_to_elements(elements_chain), many=True).data,
                )
            )
        for events in timeline_entries_map.values():
            events.reverse()
        timeline_entries = [
            TimelineEntry(sessionId=session_id, events=events)
            for session_id, events in reversed(timeline_entries_map.items())
        ]

        return SessionsTimelineQueryResponse(
            results=timeline_entries,
            hasMore=False,  # TODO
            timings=self.timings.to_list(),
            hogql=query_result.hogql,
        )

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return timedelta(minutes=1)
