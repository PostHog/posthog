from django.utils import timezone

from rest_framework import serializers

from posthog.models.notification import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for Notification model."""

    is_read = serializers.BooleanField(required=False)

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

    def to_representation(self, instance):
        """Add computed is_read field."""
        ret = super().to_representation(instance)
        ret["is_read"] = instance.read_at is not None
        return ret

    def update(self, instance, validated_data):
        """Handle is_read field by setting read_at."""
        if "is_read" in validated_data:
            is_read = validated_data.pop("is_read")
            validated_data["read_at"] = timezone.now() if is_read else None

        return super().update(instance, validated_data)
