from typing import Any, Dict

from rest_framework import serializers, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from posthog.api.routing import StructuredViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.subscription import Subscription
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission


class SubscriptionSerializer(serializers.ModelSerializer):
    """Standard Subscription serializer."""

    class Meta:
        model = Subscription
        fields = [
            "id",
            "dashboard",
            "insight",
            "target_type",
            "target_value",
            "frequency",
            "interval",
            "count",
            "start_date",
            "until_date",
            "created_at",
            "created_by",
        ]
        read_only_fields = ["id", "created_at", "created_by"]

    def validate(self, attrs):
        if not attrs.get("dashboard") and not attrs.get("insight"):
            raise ValidationError("Either dashboard or insight is required for an export.")

        if attrs.get("dashboard") and attrs["dashboard"].team.id != self.context["team_id"]:
            raise ValidationError({"dashboard": ["This dashboard does not belong to your team."]})

        if attrs.get("insight") and attrs["insight"].team.id != self.context["team_id"]:
            raise ValidationError({"insight": ["This insight does not belong to your team."]})

        return attrs

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Subscription:
        validated_data["team_id"] = self.context["team_id"]
        instance: Subscription = super().create(validated_data)

        return instance


class SubscriptionViewSet(StructuredViewSetMixin, viewsets.ModelViewSet):
    queryset = Subscription.objects.order_by("-created_at")
    serializer_class = SubscriptionSerializer

    authentication_classes = [
        PersonalAPIKeyAuthentication,
        SessionAuthentication,
        BasicAuthentication,
    ]
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]
