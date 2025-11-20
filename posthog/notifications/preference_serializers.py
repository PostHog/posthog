from rest_framework import serializers

from posthog.models.notification_preference import NotificationPreference


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    """Serializer for NotificationPreference model."""

    class Meta:
        model = NotificationPreference
        fields = [
            "id",
            "resource_type",
            "enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data):
        """Create or update preference (upsert behavior)."""
        user = self.context["request"].user
        team = self.context["team"]

        preference, created = NotificationPreference.objects.update_or_create(
            user=user,
            team=team,
            resource_type=validated_data["resource_type"],
            defaults={"enabled": validated_data["enabled"]},
        )

        return preference
