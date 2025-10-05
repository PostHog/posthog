from typing import Any

from rest_framework import serializers, viewsets

from posthog.api.feature_flag import CanEditFeatureFlag
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import ScheduledChange


class ScheduledChangeSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    failure_reason = serializers.SerializerMethodField()

    class Meta:
        model = ScheduledChange
        fields = [
            "id",
            "team_id",
            "record_id",
            "model_name",
            "payload",
            "scheduled_at",
            "executed_at",
            "failure_reason",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]

    def get_failure_reason(self, obj: ScheduledChange) -> str | None:
        """Return the safely formatted failure reason instead of raw data."""
        if not obj.failure_reason:
            return None
        return obj.formatted_failure_reason

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> ScheduledChange:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]

        # Check permissions for feature flag changes
        if validated_data.get("model_name") == "FeatureFlag":
            record_id = validated_data.get("record_id")
            if record_id:
                # Get the feature flag to check permissions
                from posthog.models import FeatureFlag

                try:
                    feature_flag = FeatureFlag.objects.get(id=record_id, team_id=validated_data["team_id"])

                    # Use the permission class to check if user can edit this feature flag
                    permission_check = CanEditFeatureFlag()
                    if not permission_check.has_object_permission(request, None, feature_flag):
                        raise serializers.ValidationError("You don't have edit permissions for this feature flag")

                except FeatureFlag.DoesNotExist:
                    raise serializers.ValidationError("Feature flag not found")

        return super().create(validated_data)


class ScheduledChangeViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update and delete scheduled changes.
    """

    scope_object = "INTERNAL"
    serializer_class = ScheduledChangeSerializer
    queryset = ScheduledChange.objects.all()

    def safely_get_queryset(self, queryset):
        model_name = self.request.query_params.get("model_name")
        record_id = self.request.query_params.get("record_id")

        if model_name is not None:
            queryset = queryset.filter(model_name=model_name)
        if record_id is not None:
            queryset = queryset.filter(record_id=record_id)

        return queryset
