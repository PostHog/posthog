"""Request checks of the dashboard widget actions."""

from collections.abc import Sequence

from rest_framework import exceptions

from products.dashboards.backend.facade.widgets import EXPECTED_WIDGET_TYPES


def parse_widget_type_filter(raw_values: Sequence[str]) -> list[str]:
    """Parse `widget_type` query values. Each value can hold one type or a comma-separated list."""
    widget_types = list(dict.fromkeys(part.strip() for raw in raw_values for part in raw.split(",") if part.strip()))
    unknown = [widget_type for widget_type in widget_types if widget_type not in EXPECTED_WIDGET_TYPES]
    if unknown:
        raise exceptions.ValidationError(
            {
                "widget_type": f"Unknown widget type: {', '.join(unknown)}. "
                f"Valid types: {', '.join(sorted(EXPECTED_WIDGET_TYPES))}."
            }
        )
    return widget_types
