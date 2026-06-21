from drf_spectacular.generators import SchemaGenerator

from products.dashboards.backend.api.dashboard import DashboardSerializer
from products.dashboards.backend.api.test.dashboard_openapi_test_helpers import (
    dashboard_patch_runtime_openapi_field_names,
)
from products.dashboards.backend.widget_specs.openapi import (
    DashboardPatchTileOpenApiSerializer,
    PatchedDashboardOpenApiSerializer,
)

# TILE_DISPLAY_FIELDS the tile PATCH schema deliberately does not expose to agents:
# filters_overrides (per-tile filter object — set via the UI, not an agent-facing knob)
# and deleted (use dashboard-delete-tile instead).
_TILE_PATCH_OPENAPI_EXCLUDED_DISPLAY_FIELDS = frozenset({"filters_overrides", "deleted"})


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

    def test_patched_dashboard_tile_documents_display_fields(self) -> None:
        # The tile PATCH schema must document the per-tile display fields the runtime accepts
        # (DashboardSerializer.TILE_DISPLAY_FIELDS). Without them, the generated MCP/agent client
        # strips layouts / show_description / color / transparent_background before the request is
        # sent, so tile resize and description toggles are silently dropped.
        tile_fields = frozenset(DashboardPatchTileOpenApiSerializer().fields.keys())
        expected = frozenset(DashboardSerializer.TILE_DISPLAY_FIELDS) - _TILE_PATCH_OPENAPI_EXCLUDED_DISPLAY_FIELDS
        missing = expected - tile_fields
        assert not missing, (
            "DashboardPatchTileOpenApiSerializer must document the agent-facing tile display fields. "
            f"Missing: {sorted(missing)}. Add the field to DashboardPatchTileOpenApiSerializer or to "
            "_TILE_PATCH_OPENAPI_EXCLUDED_DISPLAY_FIELDS with a reason."
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
