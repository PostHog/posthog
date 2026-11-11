from django.contrib import admin
from django.urls import URLPattern, path, re_path

from posthog.admin.console import views
from posthog.admin.console.moved import MovedAction, MovedToConsole
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import ConsoleRegistry, console


def moved_url_patterns(registry: ConsoleRegistry = console) -> list[URLPattern]:
    # Panels, tools and their console.py modules declare the old Django admin URLs they replaced, so a product
    # moves its own URLs without editing this file.
    patterns = []
    for moved in registry.moved():
        if isinstance(moved, MovedAction):
            view = MovedToConsole.record_redirect(RECORD_TYPES[moved.record].plural, moved.target, moved.resolver)
            patterns.append(path(moved.old_path, view))
        else:
            patterns.append(path(moved.old_path, MovedToConsole.page_redirect(moved.title, moved.url, moved.note)))
    return patterns


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
    path(
        "admin/console/tools/<slug:tool_key>/live/<slug:live_key>/",
        admin.site.admin_view(views.tool_live),
        name="admin_console_tool_live",
    ),
    path(
        "admin/console/tools/<slug:tool_key>/download/<slug:download_key>/",
        admin.site.admin_view(views.tool_download),
        name="admin_console_tool_download",
    ),
    path(
        "admin/console/tools/<slug:tool_key>/<slug:operation_key>/",
        admin.site.admin_view(views.run_tool_operation),
        name="admin_console_tool_operation",
    ),
    path(
        "admin/console/results/<slug:result_id>/",
        admin.site.admin_view(views.operation_result),
        name="admin_console_result",
    ),
    *moved_url_patterns(),
    # APPEND_SLASH is off, so a console URL typed without its trailing slash would fall through to the
    # Django admin catch-all.
    re_path(
        r"^admin/console(?P<rest>(?:/.*[^/])?)$",
        admin.site.admin_view(views.append_slash),
        name="admin_console_append_slash",
    ),
]
