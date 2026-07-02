from drf_spectacular.generators import SchemaGenerator
from rest_framework import serializers

from products.dashboards.backend.api.test.dashboard_openapi_test_helpers import (
    dashboard_patch_runtime_openapi_field_names,
)
from products.dashboards.backend.widget_specs.openapi import (
    DashboardPatchTileOpenApiSerializer,
    PatchedDashboardOpenApiSerializer,
)


def _patched_dashboard_openapi_component_properties(schema: dict) -> frozenset[str]:
    for component in schema.get("components", {}).get("schemas", {}).values():
        properties = component.get("properties")
        if not properties:
            continue
        prop_names = frozenset(properties.keys())
        if {"tiles", "breakdown_colors"}.issubset(prop_names):
            return prop_names
    raise AssertionError("PatchedDashboardOpenApi OpenAPI component not found in generated schema")


class TestDashboardPatchOpenApiContract:
    def test_patched_dashboard_openapi_covers_runtime_patch_fields(self) -> None:
        runtime_fields = dashboard_patch_runtime_openapi_field_names()
        openapi_fields = frozenset(PatchedDashboardOpenApiSerializer().fields.keys())
        missing = runtime_fields - openapi_fields
        assert not missing, (
            "PatchedDashboardOpenApiSerializer must document every agent-facing DashboardSerializer PATCH input. "
            f"Missing: {sorted(missing)}. "
            "Add the field to PatchedDashboardOpenApiSerializer or DASHBOARD_PATCH_OPENAPI_EXCLUDED_RUNTIME_FIELDS "
            "in dashboard_openapi_test_helpers.py with a reason. "
            "extend_schema(request=...) replaces the whole PATCH body — extend, do not shrink."
        )

    def test_openapi_schema_covers_runtime_patch_fields(self) -> None:
        runtime_fields = dashboard_patch_runtime_openapi_field_names()
        schema = SchemaGenerator().get_schema(request=None, public=True)
        properties = _patched_dashboard_openapi_component_properties(schema)
        missing = runtime_fields - properties
        assert not missing, (
            "Generated OpenAPI schema for dashboard PATCH must include every agent-facing runtime field. "
            f"Missing: {sorted(missing)}."
        )

    def test_tile_layouts_documented_as_writable_patch_field(self) -> None:
        # The dashboard-update MCP tool schema is generated from this serializer, and
        # extend_schema(request=...) replaces the whole PATCH body. If layouts drops off the
        # per-tile schema, the tool silently discards tile geometry — the runtime persists it
        # (test_dashboard.py::test_dashboard_item_layout) but agents can no longer send it.
        tile_fields = DashboardPatchTileOpenApiSerializer().fields
        assert "layouts" in tile_fields, (
            "DashboardPatchTileOpenApiSerializer must document 'layouts' so the dashboard-update MCP tool "
            "can resize and arrange tiles (including insight tiles) instead of silently dropping the input."
        )
        layouts_field = tile_fields["layouts"]
        assert isinstance(layouts_field, serializers.Serializer)
        breakpoint_field = layouts_field.fields["sm"]
        assert isinstance(breakpoint_field, serializers.Serializer)
        assert {"x", "y", "w", "h"}.issubset(frozenset(breakpoint_field.fields.keys())), (
            f"Tile layout breakpoint must expose x/y/w/h. Got: {sorted(breakpoint_field.fields.keys())}."
        )

    def test_filters_documented_as_writable_patch_field(self) -> None:
        # filters is a SerializerMethodField on DashboardSerializer (read-only in the inferred schema),
        # so it is excluded from dashboard_patch_runtime_openapi_field_names(). The PATCH runtime accepts and
        # persists it, so PatchedDashboardOpenApiSerializer must document it explicitly for agents/MCP.
        openapi_fields = PatchedDashboardOpenApiSerializer().fields
        assert "filters" in openapi_fields, (
            "PatchedDashboardOpenApiSerializer must document the writable 'filters' field so the dashboard-update "
            "MCP tool can set dashboard-level date/property filters."
        )
        filters_field = openapi_fields["filters"]
        assert isinstance(filters_field, serializers.Serializer)
        filters_fields = frozenset(filters_field.fields.keys())
        assert {"date_from", "date_to", "properties"}.issubset(filters_fields), (
            f"Dashboard filters schema must expose date_from/date_to/properties. Got: {sorted(filters_fields)}."
        )
