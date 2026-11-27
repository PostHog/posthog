"""Request checks of the dashboard widget actions: the API key scopes of a widget run, and the catalog's `widget_type` filter."""

from collections.abc import Sequence

from rest_framework import exceptions
from rest_framework.request import Request

from posthog.permissions import get_authenticator_scopes

from products.dashboards.backend.facade.widgets import EXPECTED_WIDGET_TYPES


def get_widget_api_scope_error(required_scopes: Sequence[str], request: Request) -> str | None:
    key_scopes = get_authenticator_scopes(request.successful_authenticator)
    if key_scopes is None:
        return None

    if "*" in key_scopes:
        return None

    for required_scope in required_scopes:
        valid_scopes = [required_scope]
        if required_scope.endswith(":read"):
            valid_scopes.append(required_scope.replace(":read", ":write"))
        if not any(scope in key_scopes for scope in valid_scopes):
            return f"API key missing required scope '{required_scope}'"
    return None


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
