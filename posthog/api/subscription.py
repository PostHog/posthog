from typing import Any, Dict

from django.db.models import QuerySet
from rest_framework import request, serializers, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from posthog.api.forbid_destroy_model import ForbidDestroyModel

from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.models.subscription import Subscription
from posthog.permissions import ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission
from posthog.utils import str_to_bool


class SubscriptionSerializer(serializers.ModelSerializer):
    """Standard Subscription serializer."""

    created_by = UserBasicSerializer(read_only=True)

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
            "deleted",
            "title",
        ]
        read_only_fields = ["id", "created_at", "created_by", "title"]

    def validate(self, attrs):
        if not self.initial_data:
            # Create
            if not attrs.get("dashboard") and not attrs.get("insight"):
                raise ValidationError("Either dashboard or insight is required for an export.")

            if attrs.get("dashboard") and attrs["dashboard"].team.id != self.context["team_id"]:
                raise ValidationError({"dashboard": ["This dashboard does not belong to your team."]})

            if attrs.get("insight") and attrs["insight"].team.id != self.context["team_id"]:
                raise ValidationError({"insight": ["This insight does not belong to your team."]})

        return attrs

    def create(self, validated_data: Dict, *args: Any, **kwargs: Any) -> Subscription:
        request = self.context["request"]
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = request.user
        instance: Subscription = super().create(validated_data)

        return instance


class SubscriptionViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer

    authentication_classes = [
        PersonalAPIKeyAuthentication,
        SessionAuthentication,
        BasicAuthentication,
    ]
    permission_classes = [IsAuthenticated, ProjectMembershipNecessaryPermissions, TeamMemberAccessPermission]

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        filters = self.request.GET.dict()

        if self.action == "list" and "deleted" not in filters:
            queryset = queryset.filter(deleted=False)

        for key in filters:
            if key == "insight_id":
                queryset = queryset.filter(insight_id=filters["insight_id"])
            elif key == "deleted":
                queryset = queryset.filter(deleted=str_to_bool(filters["deleted"]))

        return queryset
