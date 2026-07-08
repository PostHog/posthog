from __future__ import annotations

from typing import cast

from rest_framework import exceptions
from rest_framework.request import Request

from posthog.auth import IDJagAccessTokenAuthentication, OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.rbac.user_access_control import AccessControlLevel, UserAccessControl
from posthog.scopes import APIScopeObject

from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.widget_catalog import get_widget_product_access_denied_message
from products.dashboards.backend.widget_registry import WidgetRegistryEntry, get_widget_registry_entry


def _get_request_api_key_scopes(request: Request) -> list[str] | None:
    authenticator = request.successful_authenticator
    if isinstance(authenticator, PersonalAPIKeyAuthentication):
        return list(authenticator.personal_api_key.scopes or [])
    if isinstance(authenticator, OAuthAccessTokenAuthentication):
        token_scope_string = authenticator.access_token.scope
        return token_scope_string.split() if token_scope_string else []
    if isinstance(authenticator, IDJagAccessTokenAuthentication):
        return list(authenticator.scopes)
    return None


def get_widget_api_scope_error(
    registry_entry: WidgetRegistryEntry,
    request: Request,
) -> str | None:
    key_scopes = _get_request_api_key_scopes(request)
    if key_scopes is None:
        return None

    if "*" in key_scopes:
        return None

    required_scopes = registry_entry.get("required_scopes") or []
    for required_scope in required_scopes:
        valid_scopes = [required_scope]
        if required_scope.endswith(":read"):
            valid_scopes.append(required_scope.replace(":read", ":write"))
        if not any(scope in key_scopes for scope in valid_scopes):
            return f"API key missing required scope '{required_scope}'"
    return None


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


def check_widget_tile_product_access(
    widget: DashboardWidget,
    user_access_control: UserAccessControl,
) -> None:
    registry_entry = get_widget_registry_entry(widget.widget_type)
    if registry_entry is None:
        raise exceptions.PermissionDenied(f"Unknown widget type: {widget.widget_type}")

    access_error = get_widget_product_access_error(registry_entry, user_access_control)
    if access_error:
        raise exceptions.PermissionDenied(access_error)
