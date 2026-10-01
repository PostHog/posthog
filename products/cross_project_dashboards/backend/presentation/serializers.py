"""DRF serializers for cross_project_dashboards."""

from typing import Any, cast

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.models import User

from products.cross_project_dashboards.backend.facade.api import (
    CrossProjectDashboard,
    CrossProjectDashboardTile,
    assert_can_reference_insight,
    validate_cross_project_filters,
)


class CrossProjectDashboardTileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CrossProjectDashboardTile
        fields = ["id", "project_id", "insight_id", "layouts", "color", "filters_overrides"]
        read_only_fields = ["id"]
        extra_kwargs = {
            "project_id": {"help_text": "Id of the project the tile's insight belongs to."},
            "insight_id": {"help_text": "Id of the insight the tile renders."},
            "layouts": {"help_text": "Grid position and size of the tile, keyed by layout size."},
            "color": {"help_text": "Optional color applied to the tile."},
            "filters_overrides": {
                "help_text": (
                    "Filters applied to this tile only, overriding the dashboard's. Supports a date "
                    "range and an interval. Filters carrying a project-specific id are rejected."
                )
            },
        }

    def validate_filters_overrides(self, value: Any) -> dict[str, Any]:
        return validate_cross_project_filters(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Only on create: project_id and insight_id are immutable once a tile exists, so an
        # update never re-points a tile at another project.
        if self.instance is None:
            user = cast(User, self.context["request"].user)
            assert_can_reference_insight(user, attrs["project_id"], attrs["insight_id"])
        return attrs

    def update(self, instance: CrossProjectDashboardTile, validated_data: dict[str, Any]) -> CrossProjectDashboardTile:
        validated_data.pop("project_id", None)
        validated_data.pop("insight_id", None)
        return super().update(instance, validated_data)


class CrossProjectDashboardSerializer(serializers.ModelSerializer):
    """Carries tile references only.

    The response holds no insight names, queries or results. Each reader fetches each tile from
    that tile's own project endpoint, so their access, quota and cache key stay correct there.
    """

    tiles = CrossProjectDashboardTileSerializer(many=True, read_only=True)
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = CrossProjectDashboard
        fields = [
            "id",
            "name",
            "description",
            "filters",
            "tiles",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tiles", "created_by", "created_at", "updated_at"]
        extra_kwargs = {
            "name": {"help_text": "Name shown in the dashboard list and page header."},
            "description": {"help_text": "Optional longer description."},
            "filters": {
                "help_text": (
                    "Dashboard-level filters applied to every tile. Supports a date range, an "
                    "interval, and property filters that refer to a property by name. Filters "
                    "carrying a project-specific id are rejected."
                )
            },
        }

    def validate_filters(self, value: Any) -> dict[str, Any]:
        return validate_cross_project_filters(value)

    def create(self, validated_data: dict[str, Any]) -> CrossProjectDashboard:
        request = self.context["request"]
        return CrossProjectDashboard.objects.create(
            organization_id=self.context["organization_id"],
            created_by=cast(User, request.user),
            **validated_data,
        )
