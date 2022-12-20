from posthog.client import query_with_columns
from posthog.queries.time_to_see_data.serializers import (
    SessionEventSerializer,
    SessionEventsQuerySerializer,
    SessionResponseSerializer,
    UserLookup,
)

IS_FRUSTRATING_INTERACTION = "time_to_see_data_ms >= 5000"

GET_SESSIONS = f"""
SELECT
    session_id,
    any(user_id) AS user_id,
    any(team_id) AS team_id,
    min(timestamp) AS session_start,
    max(timestamp) AS session_end,
    1000 * dateDiff('second', session_start, session_end) AS duration_ms,
    argMax(team_events_last_month, _timestamp) as team_events_last_month,
    count() AS events_count,
    countIf(is_primary_interaction) AS interactions_count,
    sumIf(time_to_see_data_ms, is_primary_interaction) AS total_interaction_time_to_see_data_ms,
    countIf(is_primary_interaction and {IS_FRUSTRATING_INTERACTION}) AS frustrating_interactions_count
FROM metrics_time_to_see_data
GROUP BY session_id
ORDER BY session_end DESC
"""

GET_SESSION_EVENTS = f"""
SELECT *, {IS_FRUSTRATING_INTERACTION} AS is_frustrating
FROM metrics_time_to_see_data
WHERE team_id = %(team_id)s
  AND session_id = %(session_id)s
  AND timestamp >= %(session_start)s
  AND timestamp <= %(session_end)s
"""


def get_sessions() -> SessionResponseSerializer:
    results = query_with_columns(GET_SESSIONS)
    response_serializer = SessionResponseSerializer(
        data=results, many=True, context={"user_lookup": UserLookup(results)}
    )
    response_serializer.is_valid(raise_exception=True)
    return response_serializer


def get_session_events(query: SessionEventsQuerySerializer) -> SessionEventSerializer:
    events = query_with_columns(
        GET_SESSION_EVENTS,
        {
            "team_id": query.validated_data["team_id"],
            "session_id": query.validated_data["session_id"],
            "session_start": query.validated_data["session_start"].strftime("%Y-%m-%d %H:%M:%S"),
            "session_end": query.validated_data["session_end"].strftime("%Y-%m-%d %H:%M:%S"),
        },
    )

    response_serializer = SessionEventSerializer(data=events, many=True)
    response_serializer.is_valid(raise_exception=True)
    return response_serializer
