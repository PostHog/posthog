from functools import cached_property

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.client import query_with_columns
from posthog.models.user import User

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


class SessionResponseSerializer(serializers.Serializer):
    session_id = serializers.CharField()
    user_id = serializers.IntegerField()
    team_id = serializers.IntegerField()
    session_start = serializers.DateTimeField()
    session_end = serializers.DateTimeField()
    duration_ms = serializers.IntegerField()

    team_events_last_month = serializers.IntegerField()
    events_count = serializers.IntegerField()
    interactions_count = serializers.IntegerField()
    total_interaction_time_to_see_data_ms = serializers.IntegerField()
    frustrating_interactions_count = serializers.IntegerField()

    user = serializers.SerializerMethodField()

    def get_user(self, obj):
        user = self.context["user_lookup"].get(obj["user_id"])
        return UserBasicSerializer(user).data


class SessionEventsQuerySerializer(serializers.Serializer):
    session_id = serializers.CharField()
    team_id = serializers.IntegerField()
    session_start = serializers.DateTimeField()
    session_end = serializers.DateTimeField()


class SessionEventSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    status = serializers.CharField()

    type = serializers.CharField()
    is_primary_interaction = serializers.BooleanField()
    api_response_bytes = serializers.IntegerField()
    current_url = serializers.CharField()
    api_url = serializers.CharField()
    insight = serializers.CharField()
    action = serializers.CharField(allow_blank=True)
    insights_fetched = serializers.CharField()
    insights_fetched_cached = serializers.CharField()

    is_frustrating = serializers.BooleanField()


class UserLookup:
    def __init__(self, results):
        self.user_ids = [row["user_id"] for row in results]

    @cached_property
    def users(self):
        users = User.objects.filter(pk__in=self.user_ids)
        return {user.pk: user for user in users}

    def get(self, id):
        return self.users.get(id)


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
