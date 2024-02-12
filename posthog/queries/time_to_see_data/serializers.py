from functools import cached_property

from rest_framework import serializers

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
        from posthog.api.shared import UserBasicSerializer

        user = self.context.get("user_lookup", UserLookup([session])).get(session["user_id"])
        return UserBasicSerializer(user).data


class UserLookup:
    def __init__(self, results):
        self.user_ids = [row["user_id"] for row in results]

    @cached_property
    def users(self):
        users = User.objects.filter(pk__in=self.user_ids)
        return {user.pk: user for user in users}

    def get(self, id):
        return self.users.get(id)
