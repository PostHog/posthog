from typing import Any, cast

from django.conf import settings

from drf_spectacular.generators import SchemaGenerator

from posthog.openapi.enum_collisions import EnumCollision, find_unresolved_enum_collisions

from products.dashboards.backend.widget_registry import EXPECTED_WIDGET_TYPES

_DASHBOARD_WIDGET_ENUM_COMPONENT_MARKERS = (
    "Widget",
    "DashboardPatch",
    "AddDashboard",
)


def _is_dashboard_widget_enum_collision(collision: EnumCollision) -> bool:
    if collision["field"] != "widget_type":
        return False
    return any(
        any(marker in component_name for marker in _DASHBOARD_WIDGET_ENUM_COMPONENT_MARKERS)
        for component_name, _field_name in collision["components"]
    )


def _format_widget_enum_collisions(collisions: list[EnumCollision]) -> str:
    lines = [
        "Unresolved widget_type enum collisions in dashboard widget OpenAPI serializers.",
        "Run: python manage.py find_enum_collisions",
        "Add suggested entries to ENUM_NAME_OVERRIDES in posthog/settings/web.py",
        "",
    ]
    for collision in collisions:
        lines.append(f"  auto_name={collision['auto_name']} values={collision['values']}")
        for component_name, field_name in collision["components"]:
            lines.append(f"    - {component_name}.{field_name}")
    return "\n".join(lines)


class TestWidgetOpenApiEnumOverrides:
    def test_widget_type_enum_overrides_cover_registry(self) -> None:
        enum_overrides = cast(
            dict[str, Any],
            settings.SPECTACULAR_SETTINGS.get("ENUM_NAME_OVERRIDES", {}),
        )
        override_values = [value for value in enum_overrides.values() if isinstance(value, list)]
        for widget_type in sorted(EXPECTED_WIDGET_TYPES):
            assert [widget_type] in override_values, (
                f"Missing ENUM_NAME_OVERRIDES list entry for widget_type {widget_type!r}. "
                "Add e.g. "
                f'"{widget_type.replace("_", " ").title().replace(" ", "")}WidgetTypeEnum": ["{widget_type}"],'
            )

    def test_dashboard_widget_openapi_has_no_unresolved_widget_type_enum_collisions(self) -> None:
        schema = SchemaGenerator().get_schema(request=None, public=True)
        schemas = schema.get("components", {}).get("schemas", {})
        collisions = find_unresolved_enum_collisions(schemas)
        widget_collisions = [c for c in collisions if _is_dashboard_widget_enum_collision(c)]
        assert not widget_collisions, _format_widget_enum_collisions(widget_collisions)
