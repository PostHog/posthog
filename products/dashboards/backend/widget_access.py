from __future__ import annotations

from typing import cast

from rest_framework import exceptions

from posthog.scopes.catalog import APIScopeObject

from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.widget_catalog import get_widget_product_access_denied_message
from products.dashboards.backend.widget_registry import WidgetRegistryEntry, get_widget_registry_entry


def get_widget_product_access_error(
    registry_entry: WidgetRegistryEntry,
    user_access_control: UserAccessControl,
    *,
    required_level: AccessControlLevel = "viewer",
) -> str | None:
    required_product_access = registry_entry.get("required_product_access")
    if not required_product_access:
        return None

    if not user_access_control.check_access_level_for_resource(
        cast(APIScopeObject, required_product_access),
        required_level,
    ):
        return get_widget_product_access_denied_message(required_product_access)
    return None


def widget_product_access_error(widget_type: str, user_access_control: UserAccessControl) -> str | None:
    registry_entry = get_widget_registry_entry(widget_type)
    if registry_entry is None:
        return f"Unknown widget type: {widget_type}"
    return get_widget_product_access_error(registry_entry, user_access_control)


def check_widget_tile_product_access(
    widget: DashboardWidget,
    user_access_control: UserAccessControl,
) -> None:
    access_error = widget_product_access_error(widget.widget_type, user_access_control)
    if access_error:
        raise exceptions.PermissionDenied(access_error)
