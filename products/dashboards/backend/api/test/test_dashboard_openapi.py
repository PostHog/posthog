from drf_spectacular.generators import SchemaGenerator

from products.dashboards.backend.api.test.dashboard_openapi_test_helpers import (
    dashboard_patch_runtime_openapi_field_names,
)
from products.dashboards.backend.widget_specs.openapi import PatchedDashboardOpenApiSerializer


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
