"""Shared helpers for ``test_dashboard_openapi.py`` — not a test module itself."""

from __future__ import annotations

from rest_framework import serializers

from products.dashboards.backend.api.dashboard import DashboardSerializer

# Agent-facing dashboard PATCH fields for OpenAPI/MCP contract tests.
# Do not slim PatchedDashboardOpenApiSerializer below this set — extend_schema(request=...)
# replaces the whole PATCH body schema.
# DashboardSerializer accepts these on PATCH but they are not agent/MCP-facing OpenAPI fields.
DASHBOARD_PATCH_OPENAPI_EXCLUDED_RUNTIME_FIELDS: frozenset[str] = frozenset(
    {
        "_create_in_folder",  # create-only write_only
        "created_at",
        "deleted",
        "id",
        "last_accessed_at",
        "last_refresh",
        "team_id",
    }
)

# Accepted on PATCH but exposed as SerializerMethodField on DashboardSerializer.
_DASHBOARD_PATCH_RUNTIME_ONLY_FIELDS: frozenset[str] = frozenset({"tiles"})


def dashboard_patch_runtime_openapi_field_names() -> frozenset[str]:
    serializer = DashboardSerializer()
    read_only = frozenset(getattr(serializer.Meta, "read_only_fields", ()))
    writable: set[str] = set(_DASHBOARD_PATCH_RUNTIME_ONLY_FIELDS)
    for name, field in serializer.fields.items():
        if name in read_only:
            continue
        if isinstance(field, serializers.SerializerMethodField):
            continue
        if getattr(field, "read_only", False):
            continue
        writable.add(name)
    return frozenset(writable - DASHBOARD_PATCH_OPENAPI_EXCLUDED_RUNTIME_FIELDS)
