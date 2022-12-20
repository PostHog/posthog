from rest_framework import serializers

from posthog.client import query_with_columns

# :TODO:
IS_EVENT_AN_INTERACTION = "1"
IS_FRUSTRATING_INTERACTION = "time_to_see_data_ms >= 5000"

GET_SESSIONS = f"""
SELECT
    session_id,
    any(user_id) AS user_id,
    any(team_id) AS team_id,
    min(timestamp) AS session_start,
    max(timestamp) AS session_end,
    1000 * dateDiff('second', session_start, session_end) AS duration_ms,
    count() AS events_count,
    countIf(is_primary_interaction) AS interactions_count,
    sumIf(time_to_see_data_ms, is_primary_interaction) AS total_interaction_time_to_see_data_ms,
    countIf(is_primary_interaction and {IS_FRUSTRATING_INTERACTION}) AS frustrating_interactions_count
FROM metrics_time_to_see_data
GROUP BY session_id
ORDER BY session_end DESC
"""


class SessionResponseSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    user_id = serializers.IntegerField()
    team_id = serializers.IntegerField()
    session_start = serializers.DateTimeField()
    session_end = serializers.DateTimeField()
    duration_ms = serializers.IntegerField()

    events_count = serializers.IntegerField()
    interactions_count = serializers.IntegerField()
    total_interaction_time_to_see_data_ms = serializers.IntegerField()
    frustrating_interactions_count = serializers.IntegerField()


def get_sessions():
    results = query_with_columns(GET_SESSIONS)
    serializer = SessionResponseSerializer(data=results, many=True)
    serializer.is_valid(raise_exception=True)
    return serializer.data
