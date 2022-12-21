from functools import cached_property
from typing import List

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.models.user import User


class SessionsQuerySerializer(serializers.Serializer):
    team_id = serializers.IntegerField(required=False)
    session_id = serializers.CharField(required=False)


class SessionEventsQuerySerializer(serializers.Serializer):
    session_id = serializers.CharField()
    team_id = serializers.IntegerField()
    session_start = serializers.DateTimeField()
    session_end = serializers.DateTimeField()


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

    def get_user(self, session):
        user = self.context.get("user_lookup", UserLookup([session])).get(session["user_id"])
        return UserBasicSerializer(user).data


class SessionEventSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    status = serializers.CharField(allow_blank=True)

    type = serializers.CharField()
    is_primary_interaction = serializers.BooleanField()
    api_response_bytes = serializers.IntegerField()
    current_url = serializers.CharField()
    api_url = serializers.CharField(allow_blank=True)
    insight = serializers.CharField(allow_blank=True)
    action = serializers.CharField(allow_blank=True)
    insights_fetched = serializers.CharField()
    insights_fetched_cached = serializers.CharField()

    is_frustrating = serializers.BooleanField()


class MetricsQueryLogSerializer(serializers.Serializer):
    host = serializers.CharField()
    timestamp = serializers.DateTimeField()

    query_duration_ms = serializers.IntegerField()
    read_rows = serializers.IntegerField()
    read_bytes = serializers.IntegerField()
    result_rows = serializers.IntegerField()
    result_bytes = serializers.IntegerField()
    memory_usage = serializers.IntegerField()
    is_initial_query = serializers.BooleanField()
    exception_code = serializers.IntegerField()
    team_id = serializers.IntegerField()
    team_events_last_month = serializers.IntegerField()
    user_id = serializers.IntegerField()
    session_id = serializers.CharField()
    kind = serializers.CharField()
    query_type = serializers.CharField()
    client_query_id = serializers.CharField()
    id = serializers.CharField()
    route_id = serializers.CharField()
    query_time_range_days = serializers.CharField()
    has_json_operations = serializers.BooleanField()
    filter_by_type: serializers.ListSerializer[serializers.CharField] = serializers.ListSerializer(
        child=serializers.CharField()
    )
    breakdown_by: serializers.ListSerializer[serializers.CharField] = serializers.ListSerializer(
        child=serializers.CharField()
    )
    entity_math: serializers.ListSerializer[serializers.CharField] = serializers.ListSerializer(
        child=serializers.CharField()
    )
    filter = serializers.CharField()
    # ProfileEvents Map(String UInt64),
    tables: serializers.ListSerializer[serializers.CharField] = serializers.ListSerializer(
        child=serializers.CharField()
    )
    columns: List[str] = serializers.ListSerializer(child=serializers.CharField())
    query = serializers.CharField()

    log_comment = serializers.CharField()

    is_frustrating = serializers.BooleanField()


class SessionEventsResponseSerializer(serializers.Serializer):
    session = SessionResponseSerializer()
    events = SessionEventSerializer(many=True)
    queries = MetricsQueryLogSerializer(many=True)


class UserLookup:
    def __init__(self, results):
        self.user_ids = [row["user_id"] for row in results]

    @cached_property
    def users(self):
        users = User.objects.filter(pk__in=self.user_ids)
        return {user.pk: user for user in users}

    def get(self, id):
        return self.users.get(id)
