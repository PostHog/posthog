import asyncio
from typing import Any

import jwt
import uuid
from django.db.models import QuerySet
from django.http import HttpRequest, JsonResponse
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError

from ee.tasks import subscriptions
from ee.tasks.subscriptions import team_use_temporal_flag
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import AvailableFeature, GENERAL_PURPOSE_TASK_QUEUE
from posthog.models.subscription import Subscription, unsubscribe_using_token
from posthog.permissions import PremiumFeaturePermission
from posthog.temporal.common.client import sync_connect
from posthog.temporal.subscriptions.subscription_scheduling_workflow import (
    DeliverSubscriptionReportActivityInputs,
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

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Subscription:
        request = self.context["request"]
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = request.user

        invite_message = validated_data.pop("invite_message", "")
        instance: Subscription = super().create(validated_data)

        if not team_use_temporal_flag(instance.team):
            subscriptions.handle_subscription_value_change.delay(instance.id, "", invite_message)
        else:
            temporal = sync_connect()
            workflow_id = f"handle-subscription-value-change-{instance.id}-{uuid.uuid4()}"
            asyncio.run(
                temporal.start_workflow(
                    "handle-subscription-value-change",
                    DeliverSubscriptionReportActivityInputs(
                        subscription_id=instance.id,
                        previous_value="",
                        invite_message=invite_message,
                    ),
                    id=workflow_id,
                    task_queue=GENERAL_PURPOSE_TASK_QUEUE,
                )
            )

        return instance

    def update(self, instance: Subscription, validated_data: dict, *args, **kwargs) -> Subscription:
        previous_value = instance.target_value
        invite_message = validated_data.pop("invite_message", "")
        instance = super().update(instance, validated_data)

        if not team_use_temporal_flag(instance.team):
            subscriptions.handle_subscription_value_change.delay(instance.id, previous_value, invite_message)
        else:
            temporal = sync_connect()
            workflow_id = f"handle-subscription-value-change-{instance.id}-{uuid.uuid4()}"
            asyncio.run(
                temporal.start_workflow(
                    "handle-subscription-value-change",
                    DeliverSubscriptionReportActivityInputs(
                        subscription_id=instance.id,
                        previous_value=previous_value,
                        invite_message=invite_message,
                    ),
                    id=workflow_id,
                    task_queue=GENERAL_PURPOSE_TASK_QUEUE,
                )
            )

        return instance


class SubscriptionViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "subscription"
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [PremiumFeaturePermission]
    premium_feature = AvailableFeature.SUBSCRIPTIONS

    def safely_get_queryset(self, queryset) -> QuerySet:
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
