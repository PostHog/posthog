from django.db import transaction

from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import SyntheticMonitor
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin


class SyntheticMonitorSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

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
            "enabled",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
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
        valid_regions = {region.value for region in SyntheticMonitor.Region}
        invalid_regions = [r for r in value if r not in valid_regions]
        if invalid_regions:
            raise serializers.ValidationError(
                f"Invalid regions: {', '.join(invalid_regions)}. "
                f"Valid regions are: {', '.join(sorted(valid_regions))}"
            )
        return value

    def create(self, validated_data: dict) -> SyntheticMonitor:
        request = self.context["request"]
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = request.user

        monitor = SyntheticMonitor(**validated_data)

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

        for key, value in validated_data.items():
            setattr(instance, key, value)

        # No state changes needed - state is computed from ClickHouse events

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
            {"monitor_id": str(instance.id)},
        )

        return instance


class SyntheticMonitorViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    viewsets.ModelViewSet,
):
    scope_object = "INTERNAL"
    queryset = SyntheticMonitor.objects.select_related("created_by")
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

        # Note: State filtering would require querying ClickHouse events
        # For MVP, we skip state filtering in the queryset

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
        monitor = self.get_object()

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
                "message": "Test check triggered (execution handled by external service)",
                "monitor_id": str(monitor.id),
            },
            status=status.HTTP_200_OK,
        )
