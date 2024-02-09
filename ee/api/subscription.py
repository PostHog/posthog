from typing import Any, Dict

import jwt
from django.db.models import QuerySet
from django.http import HttpRequest, JsonResponse
from rest_framework import serializers, viewsets
from rest_framework.authentication import BasicAuthentication, SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from ee.tasks import subscriptions
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import StructuredViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.constants import AvailableFeature
from posthog.models.subscription import Subscription, unsubscribe_using_token
from posthog.permissions import (
    PremiumFeaturePermission,
    TeamMemberAccessPermission,
)
from posthog.utils import str_to_bool


class SubscriptionSerializer(serializers.ModelSerializer):
    """Standard Subscription serializer."""

    created_by = UserBasicSerializer(read_only=True)
    invite_message = serializers.CharField(required=False, allow_blank=True, allow_null=True)

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
            "byweekday",
            "bysetpos",
            "count",
            "start_date",
            "until_date",
            "created_at",
            "created_by",
            "deleted",
            "title",
            "summary",
            "next_delivery_date",
            "invite_message",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "next_delivery_date",
            "summary",
        ]

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

        invite_message = validated_data.pop("invite_message", "")
        instance: Subscription = super().create(validated_data)

        subscriptions.handle_subscription_value_change.delay(instance.id, "", invite_message)

        return instance

    def update(self, instance: Subscription, validated_data: dict, *args: Any, **kwargs: Any) -> Subscription:
        previous_value = instance.target_value
        invite_message = validated_data.pop("invite_message", "")
        instance = super().update(instance, validated_data)

        subscriptions.handle_subscription_value_change.delay(instance.id, previous_value, invite_message)

        return instance


class SubscriptionViewSet(StructuredViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer

    authentication_classes = [
        PersonalAPIKeyAuthentication,
        SessionAuthentication,
        BasicAuthentication,
    ]
    permission_classes = [
        IsAuthenticated,
        PremiumFeaturePermission,
        TeamMemberAccessPermission,
    ]
    premium_feature = AvailableFeature.SUBSCRIPTIONS

    def get_queryset(self) -> QuerySet:
        queryset = super().get_queryset()
        filters = self.request.GET.dict()

        if self.action == "list" and "deleted" not in filters:
            queryset = queryset.filter(deleted=False)

        for key in filters:
            if key == "insight":
                queryset = queryset.filter(insight_id=filters["insight"])
            if key == "dashboard":
                queryset = queryset.filter(dashboard_id=filters["dashboard"])
            elif key == "deleted":
                queryset = queryset.filter(deleted=str_to_bool(filters["deleted"]))

        return queryset


def unsubscribe(request: HttpRequest):
    token = request.GET.get("token")
    if not token:
        return JsonResponse({"success": False})

    try:
        unsubscribe_using_token(token)
    except jwt.DecodeError:
        return JsonResponse({"success": False})

    return JsonResponse({"success": True})
