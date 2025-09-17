import json
from typing import cast

from posthog.schema import (
    CachedSessionsTimelineQueryResponse,
    EventType,
    SessionsTimelineQuery,
    SessionsTimelineQueryResponse,
    TimelineEntry,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.element import ElementSerializer
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models.element.element import chain_to_elements
from posthog.utils import relative_date_parse


class SessionsTimelineQueryRunner(AnalyticsQueryRunner[SessionsTimelineQueryResponse]):
    """
    ## How does the sessions timeline work?

    A formal session on the timeline is defined as a collection of all events with a given session ID.
    An informal session is defined as a collection of contiguous events that don't have a session ID.
    Additionally, a new informal session is formed when the time between two consecutive events exceeds 30 minutes
    (which does not apply to formal sessions).

    > Note that the logic above is not the same as that of Trends session duration.
    > In Trends, only events with a session ID are considered (i.e. formal sessions).

    Now, the sessions timeline is a sequence of sessions (both formal and informal), starting with ones that started
    most recently. Events within a session are also ordered with latest first.
    """

    EVENT_LIMIT = 1000

    query: SessionsTimelineQuery
    cached_response: CachedSessionsTimelineQueryResponse

    def _get_events_subquery(self) -> ast.SelectQuery:
        after = relative_date_parse(self.query.after or "-24h", self.team.timezone_info)
        before = relative_date_parse(self.query.before or "-0h", self.team.timezone_info)
        with self.timings.measure("build_events_subquery"):
            event_conditions: list[ast.Expr] = [
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=after),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=before),
                ),
            ]
            if self.query.personId:
                event_conditions.append(
                    ast.CompareOperation(
                        left=ast.Field(chain=["person_id"]),
                        right=ast.Constant(value=self.query.personId),
                        op=ast.CompareOperationOp.Eq,
                    )
                )
            select_query = parse_select(
                """
                SELECT
                    uuid,
                    person_id AS person_id,
                    timestamp AS timestamp,
                    event,
                    properties,
                    distinct_id,
                    elements_chain,
                    $session_id AS session_id,
                    lagInFrame($session_id, 1) OVER (
                        PARTITION BY person_id ORDER BY timestamp
                    ) AS prev_session_id
                FROM events
                WHERE {event_conditions}
                ORDER BY timestamp DESC
                LIMIT {event_limit_with_more}""",
                placeholders={
                    "event_limit_with_more": ast.Constant(value=self.EVENT_LIMIT + 1),
                    "event_conditions": ast.And(exprs=event_conditions),
                },
            )
        return cast(ast.SelectQuery, select_query)

    def to_query(self) -> ast.SelectQuery:
        with self.timings.measure("build_sessions_timeline_query"):
            select_query = parse_select(
                """
                SELECT
                    e.uuid,
                    e.timestamp,
                    e.event,
                    e.properties,
                    e.distinct_id,
                    e.elements_chain,
                    e.session_id AS formal_session_id,
                    first_value(e.uuid) OVER (
                        PARTITION BY (e.person_id, session_id_flip_index) ORDER BY _toInt64(timestamp)
                        RANGE BETWEEN 1800 PRECEDING AND CURRENT ROW /* split informal session after 30+ min */
                    ) AS informal_session_uuid,
                    dateDiff('s', sre.start_time, sre.end_time) AS recording_duration_s
                FROM (
                    SELECT
                        *,
                        sum(session_id = prev_session_id ? 0 : 1) OVER (
                            PARTITION BY person_id ORDER BY timestamp ROWS UNBOUNDED PRECEDING
                        ) AS session_id_flip_index
                    FROM ({events_subquery})
                ) e
                LEFT JOIN (
                    SELECT start_time AS start_time, end_time AS end_time, session_id FROM session_replay_events
                ) AS sre
                ON e.session_id = sre.session_id
                ORDER BY timestamp DESC""",
                placeholders={"events_subquery": self._get_events_subquery()},
            )
        return cast(ast.SelectQuery, select_query)

    def to_actors_query(self):
        return parse_select(
            """SELECT DISTINCT person_id FROM {events_subquery}""", {"events_subquery": self._get_events_subquery()}
        )

    def _calculate(self) -> SessionsTimelineQueryResponse:
        query_result = execute_hogql_query(
            query=self.to_query(),
            team=self.team,
            query_type="SessionsTimelineQuery",
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        assert query_result.results is not None
        timeline_entries_map: dict[str, TimelineEntry] = {}
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
        ) in reversed(query_result.results[: self.EVENT_LIMIT]):  # The last result is a marker of more results
            entry_id = str(formal_session_id or informal_session_id)
            if entry_id not in timeline_entries_map:
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
            hasMore=len(query_result.results) > self.EVENT_LIMIT,
            timings=self.timings.to_list(),
            hogql=query_result.hogql,
        )
