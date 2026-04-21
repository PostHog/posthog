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
from rest_framework import exceptions, filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.constants import AvailableFeature
from posthog.exceptions_capture import capture_exception
from posthog.models import Insight
from posthog.models.integration import Integration
from posthog.models.subscription import Subscription, SubscriptionDelivery, unsubscribe_using_token
from posthog.permissions import PremiumFeaturePermission
from posthog.rate_limit import SubscriptionTestDeliveryThrottle
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
    summary = serializers.CharField(read_only=True, help_text="Human-readable schedule summary, e.g. 'sent daily'.")
    invite_message = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional message included in the invitation email when adding new recipients.",
    )
    integration_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID of a connected Slack integration. Required when target_type is slack.",
    )
    dashboard_export_insights = DashboardExportInsightsField(
        required=False,
        help_text="List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 6.",
    )
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
            "summary_enabled",
            "summary_prompt_guide",
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
        extra_kwargs = {
            "dashboard": {"help_text": "Dashboard ID to subscribe to (mutually exclusive with insight on create)."},
            "insight": {"help_text": "Insight ID to subscribe to (mutually exclusive with dashboard on create)."},
            "target_type": {"help_text": "Delivery channel: email, slack, or webhook."},
            "target_value": {
                "help_text": "Recipient(s): comma-separated email addresses for email, Slack channel name/ID for slack, or full URL for webhook."
            },
            "frequency": {"help_text": "How often to deliver: daily, weekly, monthly, or yearly."},
            "interval": {
                "help_text": "Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Default 1."
            },
            "byweekday": {
                "help_text": "Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday."
            },
            "bysetpos": {
                "help_text": "Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last)."
            },
            "count": {"help_text": "Total number of deliveries before the subscription stops. Null for unlimited."},
            "start_date": {"help_text": "When to start delivering (ISO 8601 datetime)."},
            "until_date": {"help_text": "When to stop delivering (ISO 8601 datetime). Null for indefinite."},
            "title": {"help_text": "Human-readable name for this subscription."},
            "deleted": {"help_text": "Set to true to soft-delete. Subscriptions cannot be hard-deleted."},
        }

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

        prompt_guide = attrs.get("summary_prompt_guide")
        if prompt_guide and len(prompt_guide) > 500:
            raise ValidationError({"summary_prompt_guide": ["AI summary context must be 500 characters or fewer."]})

        if attrs.get("summary_enabled"):
            organization = self.context["get_organization"]()
            if not organization.is_ai_data_processing_approved:
                raise exceptions.PermissionDenied(
                    "AI data processing must be approved by your organization before enabling AI summaries"
                )

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
            OpenApiParameter(
                name="insight",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by insight ID.",
            ),
            OpenApiParameter(
                name="dashboard",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by dashboard ID.",
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
    @action(
        methods=["POST"],
        detail=True,
        url_path="test-delivery",
        throttle_classes=[SubscriptionTestDeliveryThrottle],
        required_scopes=["subscription:write"],
    )
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


class SubscriptionDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionDelivery
        fields = [
            "id",
            "subscription",
            "temporal_workflow_id",
            "idempotency_key",
            "trigger_type",
            "scheduled_at",
            "target_type",
            "target_value",
            "exported_asset_ids",
            "content_snapshot",
            "recipient_results",
            "status",
            "error",
            "created_at",
            "last_updated_at",
            "finished_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Primary key for this delivery row."},
            "subscription": {"help_text": "Parent subscription id."},
            "temporal_workflow_id": {"help_text": "Temporal workflow id for this delivery run."},
            "idempotency_key": {"help_text": "Dedupes activity retries for the same logical run."},
            "trigger_type": {"help_text": "Why the run started (e.g. scheduled, manual, target_change)."},
            "scheduled_at": {"help_text": "Planned send time when applicable."},
            "target_type": {"help_text": "Channel snapshot at send time (email, slack, webhook)."},
            "target_value": {"help_text": "Destination snapshot at send time (emails, channel id, URL)."},
            "exported_asset_ids": {"help_text": "ExportedAsset ids generated for this send."},
            "content_snapshot": {
                "help_text": (
                    "Snapshot at send time: dashboard metadata, total_insight_count, and per-exported-insight "
                    "entries (id, short_id, name, query_hash, cache_key, query_results, optional query_error)."
                )
            },
            "recipient_results": {
                "help_text": "Per-destination outcomes; items use status success, failed, or partial."
            },
            "status": {"help_text": "Overall run status: starting, completed, failed, or skipped."},
            "error": {"help_text": "Top-level failure payload when status is failed, if any."},
            "created_at": {"help_text": "When the delivery row was created."},
            "last_updated_at": {"help_text": "Last ORM update to this row."},
            "finished_at": {"help_text": "When the run finished, if applicable."},
        }


class SubscriptionDeliveryCursorPagination(CursorPagination):
    page_size = 50
    ordering = "-created_at"


@extend_schema_view(
    list=extend_schema(
        summary="List subscription deliveries",
        description="Paginated delivery history for a subscription. Requires premium subscriptions.",
        parameters=[
            OpenApiParameter(
                name="status",
                type=str,
                enum=[m.value for m in SubscriptionDelivery.Status],
                location=OpenApiParameter.QUERY,
                required=False,
                description="Return only deliveries in this run status (starting, completed, failed, or skipped).",
            ),
        ],
        responses={200: OpenApiResponse(response=SubscriptionDeliverySerializer(many=True))},
    ),
    retrieve=extend_schema(
        summary="Retrieve subscription delivery",
        description="Fetch one delivery row by id.",
        responses={200: SubscriptionDeliverySerializer},
    ),
)
@extend_schema(tags=["core"])
class SubscriptionDeliveryViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "subscription"
    queryset = SubscriptionDelivery.objects.all()
    serializer_class = SubscriptionDeliverySerializer
    permission_classes = [PremiumFeaturePermission]
    premium_feature = AvailableFeature.SUBSCRIPTIONS
    pagination_class = SubscriptionDeliveryCursorPagination
    ordering = "-created_at"

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        subscription_id = self.kwargs.get("parent_lookup_subscription_id")
        if subscription_id:
            queryset = queryset.filter(subscription_id=subscription_id)
        if self.action == "list":
            status_param = self.request.query_params.get("status")
            if status_param:
                valid = {c.value for c in SubscriptionDelivery.Status}
                if status_param not in valid:
                    raise ValidationError(
                        {"status": [f"Must be one of: {', '.join(sorted(valid))}."]},
                    )
                queryset = queryset.filter(status=status_param)
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
