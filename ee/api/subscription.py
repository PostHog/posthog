import uuid
import asyncio
from typing import Any, Optional

from django.conf import settings
from django.db.models import QuerySet
from django.http import HttpRequest, JsonResponse

import jwt
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_field,
    extend_schema_view,
)
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.models import Insight
from posthog.models.integration import Integration
from posthog.models.subscription import Subscription, unsubscribe_using_token
from posthog.permissions import PremiumFeaturePermission
from posthog.security.url_validation import is_url_allowed
from posthog.temporal.common.client import sync_connect
from posthog.temporal.subscriptions.types import ProcessSubscriptionWorkflowInputs, SubscriptionTriggerType
from posthog.utils import str_to_bool

from ee.tasks.subscriptions.subscription_utils import DEFAULT_MAX_ASSET_COUNT


@extend_schema_field({"type": "array", "items": {"type": "integer"}})
class DashboardExportInsightsField(serializers.Field):
    """Custom field to handle ManyToMany dashboard_export_insights as a list of IDs."""

    def to_representation(self, value):
        return [obj.id for obj in value.all()]

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
    summary = serializers.CharField(read_only=True)
    invite_message = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    integration_id = serializers.IntegerField(required=False, allow_null=True)
    dashboard_export_insights = DashboardExportInsightsField(required=False)
    insight_short_id = serializers.SerializerMethodField()
    resource_name = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            "id",
            "dashboard",
            "insight",
            "insight_short_id",
            "resource_name",
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
            "integration_id",
            "invite_message",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "next_delivery_date",
            "summary",
            "insight_short_id",
            "resource_name",
        ]

    def get_insight_short_id(self, obj: Subscription) -> Optional[str]:
        if obj.insight_id and obj.insight is not None:
            return obj.insight.short_id
        return None

    def get_resource_name(self, obj: Subscription) -> Optional[str]:
        info = obj.resource_info
        return info.name if info else None

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

        target_type = attrs.get("target_type") or (self.instance.target_type if self.instance else None)
        integration_id = attrs.get("integration_id") or (self.instance.integration_id if self.instance else None)

        if target_type == Subscription.SubscriptionTarget.SLACK:
            if not integration_id:
                raise ValidationError({"integration_id": ["A Slack integration is required for Slack subscriptions."]})
            try:
                integration = Integration.objects.get(id=integration_id, team_id=self.context["team_id"])
            except Integration.DoesNotExist:
                raise ValidationError(
                    {"integration_id": ["This integration does not exist or does not belong to your team."]}
                )
            if integration.kind != "slack":
                raise ValidationError({"integration_id": ["Slack subscriptions require a Slack integration."]})

        # SSRF protection for webhook subscriptions
        target_value = attrs.get("target_value") or (self.instance.target_value if self.instance else None)
        if target_type == Subscription.SubscriptionTarget.WEBHOOK and target_value:
            allowed, error = is_url_allowed(target_value)
            if not allowed:
                raise ValidationError({"target_value": [f"Invalid webhook URL: {error}"]})

        return attrs

    def _validate_dashboard_export_subscription(self, attrs):
        dashboard = attrs.get("dashboard") or (self.instance.dashboard if self.instance else None)
        if dashboard is None:
            # Reject dashboard_export_insights on non dashboard subscriptions
            if attrs.get("dashboard_export_insights"):
                raise ValidationError(
                    {"dashboard_export_insights": ["Cannot set insights selection without a dashboard."]}
                )
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

            # Ensure all selected insights belong to the team
            if Insight.objects.filter(id__in=selected_ids, team_id=self.context["team_id"]).count() != len(
                selected_ids
            ):
                raise ValidationError(
                    {"dashboard_export_insights": ["Some insights do not belong to your team or do no longer exist."]}
                )

            # Ensure all selected insights belong to the dashboard (and are not deleted)
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
                ProcessSubscriptionWorkflowInputs(
                    subscription_id=instance.id,
                    team_id=instance.team_id,
                    distinct_id=str(instance.created_by.distinct_id) if instance.created_by else str(instance.team_id),
                    previous_value="",
                    invite_message=invite_message,
                    trigger_type=SubscriptionTriggerType.TARGET_CHANGE,
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
                ProcessSubscriptionWorkflowInputs(
                    subscription_id=instance.id,
                    team_id=instance.team_id,
                    distinct_id=str(instance.created_by.distinct_id) if instance.created_by else str(instance.team_id),
                    previous_value=previous_value,
                    invite_message=invite_message,
                    trigger_type=SubscriptionTriggerType.TARGET_CHANGE,
                ),
                id=workflow_id,
                task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
            )
        )

        return instance


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="created_by",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by creator user UUID.",
            ),
            OpenApiParameter(
                name="resource_type",
                type=str,
                enum=["insight", "dashboard"],
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by subscription resource: insight vs dashboard export.",
            ),
            OpenApiParameter(
                name="target_type",
                type=str,
                enum=[m.value for m in Subscription.SubscriptionTarget],
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by delivery channel (email, Slack, or webhook).",
            ),
        ],
    ),
)
@extend_schema(tags=["core"])
class SubscriptionViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "subscription"
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [PremiumFeaturePermission]
    premium_feature = AvailableFeature.SUBSCRIPTIONS
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        "title",
        "insight__name",
        "insight__derived_name",
        "dashboard__name",
    ]
    ordering_fields = [
        "created_at",
        "next_delivery_date",
        "title",
        "created_by__email",
    ]
    ordering = ["-created_at"]

    def safely_get_queryset(self, queryset) -> QuerySet:
        request_params = self.request.GET.dict()

        # Prefetch dashboard_export_insights to avoid N+1 queries in list/detail views
        queryset = queryset.prefetch_related("dashboard_export_insights")

        if self.action == "list":
            queryset = queryset.select_related("insight", "dashboard", "created_by")

            if "deleted" not in request_params:
                queryset = queryset.filter(deleted=False)

            created_by = request_params.get("created_by")
            if created_by:
                try:
                    uuid.UUID(created_by)
                except ValueError:
                    raise ValidationError({"created_by": ["Not a valid UUID."]}) from None
                queryset = queryset.filter(created_by__uuid=created_by)

            resource_type = request_params.get("resource_type")
            if resource_type == "insight":
                queryset = queryset.filter(insight_id__isnull=False)
            elif resource_type == "dashboard":
                queryset = queryset.filter(dashboard_id__isnull=False)

            target_type_filter = request_params.get("target_type")
            if target_type_filter:
                if target_type_filter not in Subscription.SubscriptionTarget.values:
                    raise ValidationError(
                        {
                            "target_type": [
                                f"Must be one of: {', '.join(sorted(Subscription.SubscriptionTarget.values))}."
                            ]
                        }
                    )
                queryset = queryset.filter(target_type=target_type_filter)

        for key in request_params:
            if key == "insight":
                queryset = queryset.filter(insight_id=request_params["insight"])
            elif key == "dashboard":
                queryset = queryset.filter(dashboard_id=request_params["dashboard"])
            elif key == "deleted":
                queryset = queryset.filter(deleted=str_to_bool(request_params["deleted"]))

        return queryset

    @extend_schema(
        request=None,
        responses={202: OpenApiResponse(description="Test delivery workflow started")},
    )
    @action(methods=["POST"], detail=True, url_path="test-delivery")
    def test_delivery(self, request, **kwargs):
        subscription = self.get_object()
        if subscription.deleted:
            return Response(status=status.HTTP_404_NOT_FOUND)

        temporal = sync_connect()
        workflow_id = f"test-delivery-subscription-{subscription.id}"
        try:
            asyncio.run(
                temporal.start_workflow(
                    "handle-subscription-value-change",
                    ProcessSubscriptionWorkflowInputs(
                        subscription_id=subscription.id,
                        team_id=subscription.team_id,
                        distinct_id=str(subscription.created_by.distinct_id)
                        if subscription.created_by
                        else str(subscription.team_id),
                        previous_value=None,
                        invite_message=None,
                        trigger_type=SubscriptionTriggerType.MANUAL,
                    ),
                    id=workflow_id,
                    task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
                )
            )
        except WorkflowAlreadyStartedError:
            return Response(
                {"detail": "Delivery already in progress"},
                status=status.HTTP_409_CONFLICT,
            )
        except Exception as e:
            capture_exception(e)
            return Response(
                {"detail": "Failed to schedule delivery"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(status=status.HTTP_202_ACCEPTED)


def unsubscribe(request: HttpRequest):
    token = request.GET.get("token")
    if not token:
        return JsonResponse({"success": False})

    try:
        unsubscribe_using_token(token)
    except jwt.DecodeError:
        return JsonResponse({"success": False})

    return JsonResponse({"success": True})
