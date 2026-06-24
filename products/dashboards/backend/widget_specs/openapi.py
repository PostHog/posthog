from __future__ import annotations

from typing import Any, cast

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from pydantic import BaseModel
from rest_framework import serializers

from products.dashboards.backend.widget_specs.pydantic_openapi import pydantic_config_field, pydantic_stub_serializer
from products.dashboards.backend.widget_specs.registry import EXPECTED_WIDGET_TYPES, WIDGET_SPECS

WIDGET_BATCH_ADD_OPENAPI_HELP = (
    "Widget tiles to add atomically. Supported widget_type values: "
    + ", ".join(sorted(EXPECTED_WIDGET_TYPES))
    + ". Use dashboard-widget-catalog-list for per-type config_schema documentation."
)


def _config_model_openapi_prefix(config_model: type[BaseModel]) -> str:
    name = config_model.__name__
    if name.endswith("WidgetConfig"):
        return name[: -len("Config")]
    if name.endswith("Config"):
        return name[: -len("Config")]
    return name


class _WidgetTileLayoutBoxOpenApiSerializer(serializers.Serializer):
    x = serializers.IntegerField(
        required=False,
        help_text="Column position in the dashboard grid (0-indexed).",
    )
    y = serializers.IntegerField(
        required=False,
        help_text="Row position in the dashboard grid (0-indexed).",
    )
    w = serializers.IntegerField(
        required=False,
        help_text="Width in grid columns. The desktop grid is 12 columns wide.",
    )
    h = serializers.IntegerField(required=False, help_text="Height in grid rows.")


class _WidgetTileLayoutsOpenApiSerializer(serializers.Serializer):
    sm = _WidgetTileLayoutBoxOpenApiSerializer(
        required=False,
        help_text="Layout for the standard (desktop) breakpoint. The grid is 12 columns wide.",
    )
    xs = _WidgetTileLayoutBoxOpenApiSerializer(
        required=False,
        help_text="Layout for the small (mobile) breakpoint. The grid is 1 column wide.",
    )


class _AddDashboardWidgetTileFieldsOpenApiSerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional custom display name for the widget tile.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional markdown description shown when show_description is enabled.",
    )
    layouts = _WidgetTileLayoutsOpenApiSerializer(
        required=False,
        help_text="Optional react-grid-layout positions keyed by breakpoint (sm, xs).",
    )
    show_description = serializers.BooleanField(
        required=False,
        help_text="Whether to show the description on the dashboard tile.",
    )


def _build_openapi_serializers() -> tuple[
    dict[str, type[serializers.Serializer]],
    dict[str, type[serializers.Serializer]],
    dict[str, type[serializers.Serializer]],
]:
    config_serializers: dict[str, type[serializers.Serializer]] = {}
    add_request_serializers: dict[str, type[serializers.Serializer]] = {}
    catalog_entry_serializers: dict[str, type[serializers.Serializer]] = {}

    for widget_type, spec in WIDGET_SPECS.items():
        config_serializer = pydantic_stub_serializer(spec.config_model)
        config_serializers[widget_type] = config_serializer

        prefix = _config_model_openapi_prefix(spec.config_model)
        add_request_serializers[widget_type] = type(
            f"{prefix}AddRequestOpenApiSerializer",
            (_AddDashboardWidgetTileFieldsOpenApiSerializer,),
            {
                "widget_type": serializers.ChoiceField(choices=[widget_type]),
                "config": pydantic_config_field(
                    spec.config_model,
                    help_text=f"Configuration for the {spec.label.lower()} widget.",
                ),
            },
        )
        catalog_entry_serializers[widget_type] = type(
            f"{prefix}CatalogEntryOpenApiSerializer",
            (serializers.Serializer,),
            {
                "widget_type": serializers.ChoiceField(choices=[widget_type]),
                "group_id": serializers.CharField(),
                "group_label": serializers.CharField(),
                "label": serializers.CharField(),
                "description": serializers.CharField(),
                "config_schema": pydantic_config_field(
                    spec.config_model,
                    read_only=True,
                    help_text=(
                        "OpenAPI config shape for this widget type (documentation; matches batch-add/PATCH schemas)."
                    ),
                ),
                "required_product_access": serializers.CharField(required=False, allow_null=True),
            },
        )

    return config_serializers, add_request_serializers, catalog_entry_serializers


WIDGET_CONFIG_SERIALIZERS, _WIDGET_ADD_REQUEST_SERIALIZERS, _WIDGET_CATALOG_ENTRY_SERIALIZERS = (
    _build_openapi_serializers()
)

DashboardWidgetConfigOpenApi = PolymorphicProxySerializer(
    component_name="DashboardWidgetConfig",
    serializers=list(WIDGET_CONFIG_SERIALIZERS.values()),
    resource_type_field_name=None,
)


@extend_schema_field(DashboardWidgetConfigOpenApi)
class DashboardWidgetConfigField(serializers.JSONField):
    """JSONField annotated with per-widget-type config schemas for OpenAPI generation."""

    pass


AddDashboardWidgetRequestOpenApi = PolymorphicProxySerializer(
    component_name="AddDashboardWidgetRequest",
    serializers=cast("dict[str, Any]", _WIDGET_ADD_REQUEST_SERIALIZERS),
    resource_type_field_name="widget_type",
)


class _UpdateDashboardWidgetTileFieldsOpenApiSerializer(serializers.Serializer):
    tile_id = serializers.IntegerField(
        help_text="ID of the widget tile to update. Use dashboard-get to look up widget tile IDs.",
    )
    name = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="New display name for the widget. Empty string or null clears it; omit to leave unchanged.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="New markdown description for the widget. Omit to leave unchanged.",
    )


def _build_update_request_serializers() -> dict[str, type[serializers.Serializer]]:
    update_request_serializers: dict[str, type[serializers.Serializer]] = {}
    for widget_type, spec in WIDGET_SPECS.items():
        prefix = _config_model_openapi_prefix(spec.config_model)
        update_request_serializers[widget_type] = type(
            f"{prefix}UpdateRequestOpenApiSerializer",
            (_UpdateDashboardWidgetTileFieldsOpenApiSerializer,),
            {
                "widget_type": serializers.ChoiceField(choices=[widget_type]),
                "config": pydantic_config_field(
                    spec.config_model,
                    required=False,
                    help_text=f"New configuration for the {spec.label.lower()} widget. Omit to leave unchanged.",
                ),
            },
        )
    return update_request_serializers


_WIDGET_UPDATE_REQUEST_SERIALIZERS = _build_update_request_serializers()

UpdateDashboardWidgetRequestOpenApi = PolymorphicProxySerializer(
    component_name="UpdateDashboardWidgetRequest",
    serializers=cast("dict[str, Any]", _WIDGET_UPDATE_REQUEST_SERIALIZERS),
    resource_type_field_name="widget_type",
)

WidgetCatalogEntryOpenApi = PolymorphicProxySerializer(
    component_name="WidgetCatalogEntry",
    serializers=cast("dict[str, Any]", _WIDGET_CATALOG_ENTRY_SERIALIZERS),
    resource_type_field_name="widget_type",
)


class WidgetCatalogResponseSerializer(serializers.Serializer):
    results = serializers.ListField(
        child=WidgetCatalogEntryOpenApi,
        help_text="Registered dashboard widget types available when dashboard-widgets is enabled.",
    )


class DashboardPatchWidgetOpenApiSerializer(serializers.Serializer):
    id = serializers.UUIDField(
        required=False,
        help_text="Existing widget row ID when updating a widget tile via dashboard PATCH.",
    )
    widget_type = serializers.ChoiceField(
        choices=sorted(EXPECTED_WIDGET_TYPES),
        required=False,
        help_text="Widget type identifier (cannot be changed on update).",
    )
    config = DashboardWidgetConfigField(
        required=False,
        help_text="Widget-specific configuration. Shape depends on the tile's widget_type.",
    )
    name = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional custom display name for the widget tile.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional markdown description shown when show_description is enabled.",
    )


class DashboardPatchTileOpenApiSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, help_text="Dashboard tile ID to update.")
    widget = DashboardPatchWidgetOpenApiSerializer(required=False, help_text="Nested widget row updates.")


class DashboardFiltersOpenApiSerializer(serializers.Serializer):
    """OpenAPI-only shape for a dashboard's filters object (agents/MCP).

    Documents the dashboard-level filters that act as the single source of truth for the
    dashboard's tiles. Runtime persistence reads the raw ``filters`` dict from the request body, so
    extra keys are accepted, but these are the ones agents should set.
    """

    date_from = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Dashboard-level start of the date range, e.g. '-30d', '-7d', or an ISO date. Applies to all tiles.",
    )
    date_to = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Dashboard-level end of the date range, e.g. '-1d' or an ISO date. Null/omitted means up to now.",
    )
    properties = serializers.JSONField(
        required=False,
        help_text="Dashboard-level property filters applied to every tile (PostHog property filter group).",
    )


class PatchedDashboardOpenApiSerializer(serializers.Serializer):
    """OpenAPI-only PATCH body for dashboards (agents/MCP).

    Must be a superset of ``dashboard_patch_runtime_openapi_field_names()`` — ``extend_schema(request=...)``
    replaces the inferred schema entirely. Contract: ``test_dashboard_openapi.py``.
    """

    name = serializers.CharField(max_length=400, required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True)
    pinned = serializers.BooleanField(required=False)
    filters = DashboardFiltersOpenApiSerializer(
        required=False,
        help_text="Dashboard-level filters (date range and properties) applied across all tiles as the source of truth.",
    )
    breakdown_colors = serializers.JSONField(
        required=False,
        help_text="Custom color mapping for breakdown values.",
    )
    data_color_theme_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID of the color theme used for chart visualizations.",
    )
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    restriction_level = serializers.ChoiceField(choices=[21, 37], required=False)
    quick_filter_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text="List of quick filter IDs associated with this dashboard.",
    )
    tiles = DashboardPatchTileOpenApiSerializer(
        many=True,
        required=False,
        help_text="Dashboard tiles to update. Widget tiles accept nested widget.config patches.",
    )
    use_template = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Template key to create the dashboard from a predefined template.",
    )
    use_dashboard = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID of an existing dashboard to duplicate.",
    )
    delete_insights = serializers.BooleanField(
        required=False,
        default=False,
        help_text="When deleting, also delete insights that are only on this dashboard.",
    )


def __getattr__(name: str) -> Any:
    for serializer in WIDGET_CONFIG_SERIALIZERS.values():
        if serializer.__name__ == name:
            return serializer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
