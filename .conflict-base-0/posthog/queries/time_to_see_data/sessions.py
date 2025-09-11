from typing import Optional

from posthog.clickhouse.client import query_with_columns
from posthog.queries.time_to_see_data.hierarchy import construct_hierarchy
from posthog.queries.time_to_see_data.serializers import (
    SessionEventsQuerySerializer,
    SessionResponseSerializer,
    SessionsQuerySerializer,
    UserLookup,
)

IS_FRUSTRATING_INTERACTION = "time_to_see_data_ms >= 5000"

GET_SESSIONS = f"""
SELECT
    session_id,
    any(user_id) AS user_id,
    any(team_id) AS team_id,
    min(timestamp - toIntervalSecond(time_to_see_data_ms / 1000)) AS session_start,
    max(timestamp) AS session_end,
    1000 * dateDiff('second', session_start, session_end) AS duration_ms,
    argMax(team_events_last_month, _timestamp) as team_events_last_month,
    count() AS events_count,
    countIf(is_primary_interaction) AS interactions_count,
    sumIf(time_to_see_data_ms, is_primary_interaction) AS total_interaction_time_to_see_data_ms,
    countIf(is_primary_interaction and {IS_FRUSTRATING_INTERACTION}) AS frustrating_interactions_count
FROM metrics_time_to_see_data
WHERE {{condition}}
GROUP BY session_id
ORDER BY session_end DESC
"""

GET_SESSION_EVENTS = f"""
SELECT *, {IS_FRUSTRATING_INTERACTION} AS is_frustrating
FROM metrics_time_to_see_data
WHERE team_id = %(team_id)s
  AND session_id = %(session_id)s
  AND timestamp >= %(session_start)s
  AND timestamp <= toDateTime(%(session_end)s) + toIntervalHour(2)
"""

GET_SESSION_QUERIES = f"""
SELECT * EXCEPT (ProfileEvents), query_duration_ms >= 5000 AS is_frustrating
FROM metrics_query_log
WHERE team_id = %(team_id)s
  AND session_id = %(session_id)s
  AND timestamp >= %(session_start)s
  AND timestamp <= toDateTime(%(session_end)s) + toIntervalHour(2)
"""


def get_sessions(query: SessionsQuerySerializer) -> SessionResponseSerializer:
    sessions = _fetch_sessions(query)
    response_serializer = SessionResponseSerializer(
        data=sessions, many=True, context={"user_lookup": UserLookup(sessions)}
    )
    response_serializer.is_valid(raise_exception=True)
    return response_serializer


def get_session_events(query: SessionEventsQuerySerializer) -> Optional[dict]:
    params = {
        "team_id": query.validated_data["team_id"],
        "session_id": query.validated_data["session_id"],
        "session_start": query.validated_data["session_start"].strftime("%Y-%m-%d %H:%M:%S"),
        "session_end": query.validated_data["session_end"].strftime("%Y-%m-%d %H:%M:%S"),
    }
    events = query_with_columns(GET_SESSION_EVENTS, params)
    queries = query_with_columns(GET_SESSION_QUERIES, params)
    session_query = SessionsQuerySerializer(
        data={
            "team_id": query.validated_data["team_id"],
            "session_id": query.validated_data["session_id"],
        }
    )
    session_query.is_valid(raise_exception=True)
    sessions = get_sessions(session_query).data

    if len(sessions) == 0:
        return None

    return construct_hierarchy(sessions[0], events, queries)


def _fetch_sessions(query: SessionsQuerySerializer) -> list[dict]:
    condition, params = _sessions_condition(query)
    return query_with_columns(GET_SESSIONS.format(condition=condition), params)


def _sessions_condition(query: SessionsQuerySerializer) -> tuple[str, dict]:
    conditions = []

    if "team_id" in query.validated_data:
        conditions.append("metrics_time_to_see_data.team_id = %(team_id)s")

    if "session_id" in query.validated_data:
        conditions.append("metrics_time_to_see_data.session_id = %(session_id)s")

    if len(conditions) > 0:
        return " AND ".join(conditions), query.validated_data
    else:
        return "1 = 1", {}
