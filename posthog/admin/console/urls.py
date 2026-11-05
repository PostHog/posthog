from django.contrib import admin
from django.urls import path, re_path

from posthog.admin.console import views
from posthog.admin.console.moved import MovedToConsole
from posthog.admin.console.records import RECORD_TYPES

# Old Django admin URLs of team actions that moved. Staff keep bookmarks to them, query parameters included.
MOVED_TEAM_ACTIONS = {
    "set-api-token": "api-token/set/",
    "add-ai-gateway-credit": "ai-gateway/add-credit/",
    "set-email-sending-tier": "email-sending/set-tier/",
    "rebuild-cache": "#panel-remote-config",
    "enable-ai-gateway": "#panel-ai-gateway",
    "revoke-ai-gateway": "#panel-ai-gateway",
    "clear-ai-gateway-revoke": "#panel-ai-gateway",
    "recompute-email-sending-tier": "#panel-email-sending",
}

MOVED_ORGANIZATION_ACTIONS = {
    "limit-product": "#panel-billing",
    "unlimit-product": "#panel-billing",
    "sync-to-billing": "#panel-billing",
}

# Every route sits under /admin/, so AdminOAuth2Middleware adds its Google step-up, and admin_view
# adds the staff check, the login redirect and CSRF protection. The console needs no auth of its own.
urlpatterns = [
    path("admin/console/", admin.site.admin_view(views.console_home), name="admin_console_home"),
    *[
        route
        for record_type in RECORD_TYPES.values()
        for route in (
            path(
                f"admin/console/{record_type.plural}/<{record_type.pk_converter}:pk>/",
                admin.site.admin_view(views.record_detail),
                {"record": record_type.key},
                name=record_type.url_name,
            ),
            path(
                f"admin/console/{record_type.plural}/<{record_type.pk_converter}:pk>/<slug:panel_key>/<slug:operation_key>/",
                admin.site.admin_view(views.run_operation),
                {"record": record_type.key},
                name=record_type.operation_url_name,
            ),
        )
    ],
    path(
        "admin/console/tools/<slug:tool_key>/",
        admin.site.admin_view(views.tool_page),
        name="admin_console_tool",
    ),
    *[
        path(
            f"admin/posthog/team/<int:pk>/{old}/",
            admin.site.admin_view(MovedToConsole.record_redirect("teams", target)),
        )
        for old, target in MOVED_TEAM_ACTIONS.items()
    ],
    *[
        path(
            f"admin/posthog/organization/<uuid:pk>/{old}/",
            admin.site.admin_view(MovedToConsole.record_redirect("organizations", target)),
        )
        for old, target in MOVED_ORGANIZATION_ACTIONS.items()
    ],
    # APPEND_SLASH is off, so a console URL typed without its trailing slash would fall through to the
    # Django admin catch-all.
    re_path(
        r"^admin/console(?P<rest>(?:/.*[^/])?)$",
        admin.site.admin_view(views.append_slash),
        name="admin_console_append_slash",
    ),
]
