import logging
from typing import Any

from django.db import transaction

from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.team.team_data_warehouse_config import TeamDataWarehouseConfig
from posthog.warehouse.models.managed_view import (
    create_revenue_analytics_managed_views,
    delete_revenue_analytics_managed_views,
)

logger = logging.getLogger(__name__)


class DataWarehouseConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamDataWarehouseConfig
        fields = ["revenue_analytics_package_view_enabled_at"]

    def update(self, instance: TeamDataWarehouseConfig, validated_data: dict[str, Any]) -> TeamDataWarehouseConfig:
        """Update the data warehouse config and handle managed view creation/deletion."""
        old_revenue_analytics_enabled_at = instance.revenue_analytics_package_view_enabled_at
        new_revenue_analytics_enabled_at = validated_data.get("revenue_analytics_package_view_enabled_at")

        with transaction.atomic():
            # Update the config
            updated_instance = super().update(instance, validated_data)

            # Handle managed view creation/deletion based on the change
            if old_revenue_analytics_enabled_at is None and new_revenue_analytics_enabled_at is not None:
                # Revenue analytics was just enabled - create managed views
                logger.info(f"Revenue analytics enabled for team {instance.team.id}, creating managed views")
                create_revenue_analytics_managed_views(instance.team)
            elif old_revenue_analytics_enabled_at is not None and new_revenue_analytics_enabled_at is None:
                # Revenue analytics was just disabled - delete managed views
                logger.info(f"Revenue analytics disabled for team {instance.team.id}, deleting managed views")
                delete_revenue_analytics_managed_views(instance.team)

        return updated_instance


class DataWarehouseConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Manage data warehouse configuration for a team.
    """

    scope_object = "INTERNAL"
    serializer_class = DataWarehouseConfigSerializer
    lookup_field = "team_id"
    queryset = TeamDataWarehouseConfig.objects.all()

    def safely_get_object(self):
        return self.team.data_warehouse_config

    def list(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Get the data warehouse config for the team."""
        config = self.safely_get_object()
        serializer = self.get_serializer(config)
        return response.Response(serializer.data)

    def update(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Update the data warehouse config and handle managed view creation/deletion."""
        config = self.safely_get_object()
        serializer = self.get_serializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return response.Response(serializer.data)

    def partial_update(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Partially update the data warehouse config."""
        return self.update(request, *args, **kwargs)

    @action(methods=["POST"], detail=False)
    def toggle_revenue_analytics(self, request: request.Request, *args, **kwargs) -> response.Response:
        """Toggle revenue analytics package views on/off or set to specific value."""
        from django.utils import timezone

        config = self.safely_get_object()
        current_enabled = config.revenue_analytics_package_view_enabled_at is not None

        # Check if a specific value was provided
        enabled = request.data.get("enabled")
        if enabled is None:
            # No specific value provided, toggle the current state
            enabled = not current_enabled
        elif isinstance(enabled, str):
            # Handle string values like "true"/"false"
            enabled = enabled.lower() in ("true", "1", "yes", "on")

        # Determine the new timestamp value
        if enabled:
            new_value = timezone.now()
        else:
            new_value = None

        # Use the serializer to handle the update and managed view creation/deletion
        serializer = self.get_serializer(config, data={"revenue_analytics_package_view_enabled_at": new_value})
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return response.Response(serializer.data)
