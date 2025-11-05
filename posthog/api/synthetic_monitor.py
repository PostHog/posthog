from django.db import transaction

from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import Integration, SyntheticMonitor, User
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin


class SyntheticMonitorSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    alert_recipient_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=User.objects.all(), source="alert_recipients", required=False, allow_null=True
    )
    slack_integration_id = serializers.PrimaryKeyRelatedField(
        queryset=Integration.objects.all(), source="slack_integration", required=False, allow_null=True
    )

    class Meta:
        model = SyntheticMonitor
        fields = [
            "id",
            "name",
            "url",
            "frequency_minutes",
            "regions",
            "method",
            "headers",
            "body",
            "expected_status_code",
            "timeout_seconds",
            "alert_enabled",
            "alert_threshold_failures",
            "alert_recipient_ids",
            "slack_integration_id",
            "enabled",
            "state",
            "last_checked_at",
            "next_check_at",
            "consecutive_failures",
            "last_alerted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "state",
            "last_checked_at",
            "next_check_at",
            "consecutive_failures",
            "last_alerted_at",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_url(self, value: str) -> str:
        if not value.startswith("http://") and not value.startswith("https://"):
            raise serializers.ValidationError("URL must start with http:// or https://")
        return value

    def validate_method(self, value: str) -> str:
        allowed_methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
        if value.upper() not in allowed_methods:
            raise serializers.ValidationError(f"Method must be one of {', '.join(allowed_methods)}")
        return value.upper()

    def validate_regions(self, value: list) -> list:
        if not isinstance(value, list):
            raise serializers.ValidationError("Regions must be a list")
        if len(value) == 0:
            return value
        if not all(isinstance(region, str) for region in value):
            raise serializers.ValidationError("All regions must be strings")
        return value

    def validate_slack_integration_id(self, value: Integration | None) -> Integration | None:
        if value and value.kind != "slack":
            raise serializers.ValidationError("Integration must be a Slack integration")
        return value

    def create(self, validated_data: dict) -> SyntheticMonitor:
        request = self.context["request"]
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = request.user

        # Calculate initial next_check_at
        monitor = SyntheticMonitor(**validated_data)
        monitor.update_next_check()

        with transaction.atomic():
            monitor.save()

        report_user_action(
            request.user,
            "synthetic monitor created",
            {
                "monitor_id": str(monitor.id),
                "frequency_minutes": monitor.frequency_minutes,
            },
        )

        return monitor

    def update(self, instance: SyntheticMonitor, validated_data: dict) -> SyntheticMonitor:
        request = self.context["request"]

        # Track if enabled status is changing
        enabled_changed = "enabled" in validated_data and validated_data["enabled"] != instance.enabled

        # If frequency changed, recalculate next_check_at
        frequency_changed = (
            "frequency_minutes" in validated_data and validated_data["frequency_minutes"] != instance.frequency_minutes
        )

        for key, value in validated_data.items():
            setattr(instance, key, value)

        # Handle enabled state changes
        if enabled_changed:
            if instance.enabled:
                # Resuming: set to healthy and schedule next check
                instance.state = SyntheticMonitor.MonitorState.HEALTHY
                instance.update_next_check()
            else:
                # Pausing: set to disabled
                instance.state = SyntheticMonitor.MonitorState.DISABLED

        if frequency_changed:
            instance.update_next_check()

        with transaction.atomic():
            instance.save()

        action = (
            "synthetic monitor resumed"
            if enabled_changed and instance.enabled
            else (
                "synthetic monitor paused" if enabled_changed and not instance.enabled else "synthetic monitor updated"
            )
        )
        report_user_action(
            request.user,
            action,
            {
                "monitor_id": str(instance.id),
            },
        )

        return instance


class SyntheticMonitorViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    viewsets.ModelViewSet,
):
    scope_object = "INTERNAL"
    queryset = SyntheticMonitor.objects.select_related("created_by", "slack_integration").prefetch_related(
        "alert_recipients"
    )
    serializer_class = SyntheticMonitorSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "url"]
    access_control_level_filters = {}

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(team_id=self.team_id)

        # Optionally filter by enabled status
        enabled = self.request.query_params.get("enabled")
        if enabled is not None:
            queryset = queryset.filter(enabled=enabled.lower() == "true")

        # Optionally filter by state
        state = self.request.query_params.get("state")
        if state:
            queryset = queryset.filter(state=state)

        # Optionally filter by type
        monitor_type = self.request.query_params.get("type")
        if monitor_type:
            queryset = queryset.filter(type=monitor_type)

        return queryset.order_by("-created_at")

    def perform_destroy(self, instance: SyntheticMonitor):
        report_user_action(
            self.request.user,
            "synthetic monitor deleted",
            {
                "monitor_id": str(instance.id),
                "monitor_name": instance.name,
            },
        )
        instance.delete()

    @action(methods=["POST"], detail=True)
    def test(self, request: Request, **kwargs) -> Response:
        """Trigger an immediate test check of the monitor"""
        from posthog.tasks.alerts.synthetic_monitoring import execute_http_check

        monitor = self.get_object()

        # Trigger immediate check
        execute_http_check.delay(monitor_id=str(monitor.id))

        report_user_action(
            request.user,
            "synthetic monitor test triggered",
            {
                "monitor_id": str(monitor.id),
            },
        )

        return Response(
            {
                "success": True,
                "message": "Test check triggered",
                "monitor_id": str(monitor.id),
            },
            status=status.HTTP_200_OK,
        )
