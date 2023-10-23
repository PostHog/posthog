from datetime import timedelta
import json
from typing import Dict, Optional, Any, cast
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
    """
    # How does the sessions timeline work?

    A formal session on the timeline is defined by finding the first and last event with a given session ID, and
    collecting these events and all in between.
    An informal session is defined by collecting all events between formal sessions, where a new informal session is
    formed when the time between two events exceeds 30 minutes. These sessions only contain events without a session ID.

    > This is not the same as the Trends session duration logic, where events without a session ID are ignored.

    The sessions timeline is a sequence of sessions (both formal and informal), starting with ones that started most
    recently. Events within a session are also ordered by timestamp descending.
    """

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
                        FROM events AS e
                        WHERE e.timestamp > toDateTime({after}) AND e.timestamp <= toDateTime({before})
                        ORDER BY timestamp DESC
                        LIMIT 1000
                    ) AS relevant_session_ids
                    SELECT
                        e.uuid,
                        e.timestamp,
                        e.event,
                        e.properties,
                        e.distinct_id,
                        e.elements_chain,
                        e.$session_id AS formal_session_id,
                        first_value(e.uuid) OVER (
                            PARTITION BY $session_id ORDER BY __toInt64(timestamp) / 60e6 /* µs converted to min */
                            RANGE BETWEEN 1800 PRECEDING AND CURRENT ROW
                        ) AS informal_session_uuid,
                        dateDiff('s', sre.start_time, sre.end_time) AS recording_duration_s
                    FROM events AS e
                    LEFT JOIN (
                        SELECT start_time, end_time, session_id FROM session_replay_events
                    ) AS sre
                    ON e.$session_id = sre.session_id
                    WHERE
                        e.timestamp >= (
                            SELECT min(timestamp)
                            FROM events AS e
                            WHERE e.$session_id IN relevant_session_ids OR (
                                $session_id IS NULL
                                AND e.timestamp > toDateTime({after}) AND e.timestamp < toDateTime({before})
                            )
                        )
                        AND e.timestamp <= (
                            SELECT max(timestamp)
                            FROM events AS e
                            WHERE e.$session_id IN relevant_session_ids OR (
                                $session_id IS NULL
                                AND e.timestamp > toDateTime({after}) AND e.timestamp < toDateTime({before})
                            )
                        )
                    ORDER BY timestamp DESC
                    LIMIT 1000""",
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
                    left=ast.Field(chain=["e", "person_id"]),
                    right=ast.Constant(value=self.query.personId),
                    op=ast.CompareOperationOp.Eq,
                )
                select_query.where = ast.CompareOperation(
                    left=ast.Field(chain=["e", "person_id"]),
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
        timeline_entries_map: Dict[str, TimelineEntry] = {}
        for (
            uuid,
            timestamp_parsed,
            event,
            properties_raw,
            distinct_id,
            elements_chain,
            formal_session_id,
            informal_session_id,
            recording_duration_s,
        ) in reversed(query_result.results):
            entry_id = str(formal_session_id or informal_session_id)
            if entry_id not in reversed(timeline_entries_map):
                timeline_entries_map[entry_id] = TimelineEntry(
                    sessionId=formal_session_id or None, events=[], recording_duration_s=recording_duration_s or None
                )
            timeline_entries_map[entry_id].events.append(
                EventType(
                    id=str(uuid),
                    distinct_id=distinct_id,
                    event=event,
                    timestamp=timestamp_parsed.isoformat(),
                    properties=json.loads(properties_raw),
                    elements_chain=elements_chain or None,
                    elements=ElementSerializer(chain_to_elements(elements_chain), many=True).data,
                )
            )
        timeline_entries = list(reversed(timeline_entries_map.values()))
        for entry in timeline_entries:
            entry.events.reverse()

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
