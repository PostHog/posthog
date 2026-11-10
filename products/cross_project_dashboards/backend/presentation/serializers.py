"""DRF serializers for cross_project_dashboards. They convert JSON to and from facade contracts."""

import json
from typing import Any

from rest_framework import serializers

from ..facade.api import validate_cross_project_filters

TILE_FILTERS_HELP = (
    "Filters applied to this tile only, overriding the dashboard's. Supports a date range and an interval. "
    "Filters carrying a project-specific id are rejected."
)
# Every list page carries these blobs, so each one has a size ceiling.
MAX_DASHBOARD_FILTERS_BYTES = 16_384
MAX_TILE_JSON_BYTES = 4_096


def _within(value: Any, max_bytes: int) -> Any:
    if len(json.dumps(value)) > max_bytes:
        raise serializers.ValidationError(f"Keep this under {max_bytes} bytes.")
    return value


DASHBOARD_FILTERS_HELP = (
    "Dashboard-level filters applied to every tile. Supports a date range, an interval, and property filters "
    "that refer to a property by name. Filters carrying a project-specific id are rejected."
)


class CrossProjectDashboardTileSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Id of the tile.")
    project_id = serializers.IntegerField(help_text="Id of the project the tile's insight belongs to.")
    insight_id = serializers.IntegerField(help_text="Id of the insight the tile renders.")
    layouts = serializers.JSONField(default=dict, help_text="Grid position and size of the tile, keyed by layout size.")
    color = serializers.CharField(
        default=None, allow_null=True, allow_blank=True, max_length=400, help_text="Optional color applied to the tile."
    )
    filters_overrides = serializers.JSONField(default=dict, help_text=TILE_FILTERS_HELP)

    def validate_layouts(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise serializers.ValidationError("Layouts must be an object keyed by layout size.")
        return _within(value, MAX_TILE_JSON_BYTES)

    def validate_filters_overrides(self, value: Any) -> dict[str, Any]:
        return validate_cross_project_filters(_within(value, MAX_TILE_JSON_BYTES))


class CrossProjectDashboardTileUpdateSerializer(serializers.Serializer):
    """A tile's project and insight never change, so an update carries only its placement and styling."""

    layouts = serializers.JSONField(
        required=False, help_text="Grid position and size of the tile, keyed by layout size."
    )
    color = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        max_length=400,
        help_text="Optional color applied to the tile.",
    )
    filters_overrides = serializers.JSONField(required=False, help_text=TILE_FILTERS_HELP)

    def validate_layouts(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise serializers.ValidationError("Layouts must be an object keyed by layout size.")
        return _within(value, MAX_TILE_JSON_BYTES)

    def validate_filters_overrides(self, value: Any) -> dict[str, Any]:
        return validate_cross_project_filters(_within(value, MAX_TILE_JSON_BYTES))


class CrossProjectDashboardCreatorSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True, help_text="Id of the user who created the dashboard.")
    first_name = serializers.CharField(read_only=True, help_text="First name of the user who created the dashboard.")
    email = serializers.EmailField(read_only=True, help_text="Email of the user who created the dashboard.")


class CrossProjectDashboardListItemSerializer(serializers.Serializer):
    """A dashboard in the list. It counts its tiles instead of carrying them; read one dashboard for its tiles."""

    id = serializers.UUIDField(read_only=True, help_text="Id of the dashboard.")
    name = serializers.CharField(read_only=True, help_text="Name shown in the dashboard list and page header.")
    description = serializers.CharField(read_only=True, help_text="Optional longer description.")
    filters = serializers.JSONField(read_only=True, help_text=DASHBOARD_FILTERS_HELP)
    tile_count = serializers.IntegerField(read_only=True, help_text="Tiles from the projects the reader can open.")
    project_count = serializers.IntegerField(
        read_only=True, help_text="Distinct projects among the tiles the reader can open."
    )
    created_by = CrossProjectDashboardCreatorSerializer(
        read_only=True, allow_null=True, help_text="The user who created the dashboard."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the dashboard was created.")
    updated_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the dashboard last changed."
    )


class CrossProjectDashboardSerializer(serializers.Serializer):
    """Carries tile references only.

    The response holds no insight names, queries or results. Each reader fetches each tile from
    that tile's own project endpoint, so their access, quota and cache key stay correct there.
    """

    id = serializers.UUIDField(read_only=True, help_text="Id of the dashboard.")
    name = serializers.CharField(max_length=400, help_text="Name shown in the dashboard list and page header.")
    description = serializers.CharField(
        allow_blank=True, default="", max_length=4000, help_text="Optional longer description."
    )
    filters = serializers.JSONField(default=dict, help_text=DASHBOARD_FILTERS_HELP)
    tiles = CrossProjectDashboardTileSerializer(
        many=True, read_only=True, help_text="Tiles from the projects the reader can open."
    )
    created_by = CrossProjectDashboardCreatorSerializer(
        read_only=True, allow_null=True, help_text="The user who created the dashboard."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the dashboard was created.")
    updated_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the dashboard last changed."
    )

    def validate_filters(self, value: Any) -> dict[str, Any]:
        return validate_cross_project_filters(_within(value, MAX_DASHBOARD_FILTERS_BYTES))
