import uuid
import asyncio
from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.http import HttpRequest, JsonResponse

import jwt
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import AvailableFeature
from posthog.models.subscription import Subscription, unsubscribe_using_token
from posthog.permissions import PremiumFeaturePermission
from posthog.security.url_validation import is_url_allowed
from posthog.temporal.common.client import sync_connect
from posthog.temporal.subscriptions.subscription_scheduling_workflow import DeliverSubscriptionReportActivityInputs
from posthog.utils import str_to_bool

from ee.tasks.subscriptions.subscription_utils import DEFAULT_MAX_ASSET_COUNT


@extend_schema_field({"type": "array", "items": {"type": "integer"}})
class DashboardExportInsightsField(serializers.Field):
    """Custom field to handle ManyToMany dashboard_export_insights as a list of IDs."""

    def to_representation(self, value):
        return list(value.values_list("id", flat=True))

    def to_internal_value(self, data):
        if not isinstance(data, list):
            raise serializers.ValidationError("Expected a list of insight IDs.")
        for item in data:
            if not isinstance(item, int):
                raise serializers.ValidationError("All items must be integers.")
        return data


class SubscriptionSerializer(serializers.ModelSerializer):
    """Standard Subscription serializer."""

    created_by = UserBasicSerializer(read_only=True)
    invite_message = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    dashboard_export_insights = DashboardExportInsightsField(required=False)

    class Meta:
        model = Subscription
        fields = [
            "id",
            "dashboard",
            "insight",
            "dashboard_export_insights",
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

        self._validate_dashboard_export_subscription(attrs)

        # SSRF protection for webhook subscriptions
        target_type = attrs.get("target_type") or (self.instance.target_type if self.instance else None)
        target_value = attrs.get("target_value") or (self.instance.target_value if self.instance else None)
        if target_type == Subscription.SubscriptionTarget.WEBHOOK and target_value:
            allowed, error = is_url_allowed(target_value)
            if not allowed:
                raise ValidationError({"target_value": [f"Invalid webhook URL: {error}"]})

        return attrs

    def _validate_dashboard_export_subscription(self, attrs):
        dashboard = attrs.get("dashboard") or (self.instance.dashboard if self.instance else None)
        if dashboard is None:
            return

        # For PATCH requests, dashboard_export_insights might not be in attrs - only validate if provided or on create
        dashboard_export_insights_provided = "dashboard_export_insights" in attrs
        dashboard_export_insights = attrs.get("dashboard_export_insights", [])

        is_create = self.instance is None
        if (
            # For new dashboard subscriptions, require at least one insight to be selected
            (is_create and not dashboard_export_insights)
            or
            # If updating and explicitly setting dashboard_export_insights to empty, reject it
            (not is_create and dashboard_export_insights_provided and not dashboard_export_insights)
        ):
            raise ValidationError({"dashboard_export_insights": ["Select at least one insight for this subscription."]})

        if dashboard_export_insights:
            selected_ids = set(dashboard_export_insights)

            if len(selected_ids) > DEFAULT_MAX_ASSET_COUNT:
                raise ValidationError(
                    {"dashboard_export_insights": [f"Cannot select more than {DEFAULT_MAX_ASSET_COUNT} insights."]}
                )

            # If dashboard is set, ensure all selected insights belong to it (and are not deleted)
            dashboard_insight_ids = set(
                dashboard.tiles.filter(insight__isnull=False, insight__deleted=False).values_list(
                    "insight_id", flat=True
                )
            )
            invalid_ids = selected_ids - dashboard_insight_ids

            if invalid_ids:
                raise ValidationError(
                    {"dashboard_export_insights": [f"{len(invalid_ids)} invalid insight(s) selected."]}
                )

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> Subscription:
        request = self.context["request"]
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = request.user

        invite_message = validated_data.pop("invite_message", "")
        dashboard_export_insight_ids = validated_data.pop("dashboard_export_insights", [])
        instance: Subscription = super().create(validated_data)

        if dashboard_export_insight_ids:
            instance.dashboard_export_insights.set(dashboard_export_insight_ids)

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
                task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            )
        )

        return instance

    def update(self, instance: Subscription, validated_data: dict, *args, **kwargs) -> Subscription:
        previous_value = instance.target_value
        invite_message = validated_data.pop("invite_message", "")
        dashboard_export_insight_ids = validated_data.pop("dashboard_export_insights", [])
        instance = super().update(instance, validated_data)

        if dashboard_export_insight_ids:
            instance.dashboard_export_insights.set(dashboard_export_insight_ids)

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
                task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            )
        )

        return instance


@extend_schema(tags=["core"])
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
