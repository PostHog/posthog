from rest_framework import serializers

from posthog.models.notification import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for Notification model."""

    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "resource_type",
            "resource_id",
            "title",
            "message",
            "context",
            "priority",
            "is_read",
            "read_at",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_is_read(self, obj: Notification) -> bool:
        return obj.read_at is not None
