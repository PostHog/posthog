from rest_framework import serializers

from posthog.models import User


class UserMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["first_name", "email"]


class ChangeSerializer(serializers.Serializer):
    type = serializers.CharField(read_only=True)
    action = serializers.CharField(read_only=True)
    field = serializers.CharField(read_only=True)
    before = serializers.JSONField(read_only=True)
    after = serializers.JSONField(read_only=True)


class MergeSerializer(serializers.Serializer):
    type = serializers.CharField(read_only=True)
    # mypy being weird about this specific field
    source = serializers.JSONField(read_only=True)  # type: ignore
    target = serializers.JSONField(read_only=True)


class DetailSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True)
    changes = ChangeSerializer(many=True)
    merge = MergeSerializer(required=False)
    name = serializers.CharField(read_only=True)
    short_id = serializers.CharField(read_only=True)


class ActivityLogSerializer(serializers.Serializer):
    class Meta:
        exclude = ["team_id, organization_id"]

    user = UserMinimalSerializer(read_only=True)
    activity = serializers.CharField(read_only=True)
    scope = serializers.CharField(read_only=True)
    item_id = serializers.CharField(read_only=True)
    detail = DetailSerializer(required=False)
    created_at = serializers.DateTimeField(read_only=True)
