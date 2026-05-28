from __future__ import annotations

from rest_framework.request import Request

from posthog.rbac.user_access_control import UserAccessControl

from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.widget_registry import WidgetRegistryEntry, get_widget_registry_entry

PRODUCT_ACCESS_DENIED_MESSAGES: dict[str, str] = {
    # Optional friendly denial copy for registry `required_product_access` keys — see CONTRIBUTING.md.
    "error_tracking": "You do not have access to error tracking.",
    "session_recording": "You do not have access to session replay.",
}


def get_widget_product_access_denied_message(required_product_access: str) -> str:
    return PRODUCT_ACCESS_DENIED_MESSAGES.get(
        required_product_access,
        f"You do not have access to {required_product_access.replace('_', ' ')}.",
    )


def _get_request_api_key_scopes(request: Request) -> list[str] | None:
    from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication

    authenticator = request.successful_authenticator
    if isinstance(authenticator, PersonalAPIKeyAuthentication):
        return list(authenticator.personal_api_key.scopes or [])
    if isinstance(authenticator, OAuthAccessTokenAuthentication):
        token_scope_string = authenticator.access_token.scope
        return token_scope_string.split() if token_scope_string else []
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
    required_level: str = "viewer",
) -> str | None:
    required_product_access = registry_entry.get("required_product_access")
    if not required_product_access:
        return None

    if not user_access_control.check_access_level_for_resource(
        required_product_access,
        required_level,  # type: ignore[arg-type]
    ):
        return get_widget_product_access_denied_message(required_product_access)
    return None


def check_widget_tile_product_access(
    widget: DashboardWidget,
    user_access_control: UserAccessControl,
) -> None:
    from rest_framework import exceptions

    registry_entry = get_widget_registry_entry(widget.widget_type)
    if registry_entry is None:
        raise exceptions.PermissionDenied(f"Unknown widget type: {widget.widget_type}")

    access_error = get_widget_product_access_error(registry_entry, user_access_control)
    if access_error:
        raise exceptions.PermissionDenied(access_error)
