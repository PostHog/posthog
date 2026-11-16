from django.contrib import admin
from django.urls import path, re_path

from posthog.admin.console import views

# Every route sits under /admin/, so AdminOAuth2Middleware adds its Google step-up, and admin_view
# adds the staff check, the login redirect and CSRF protection. The console needs no auth of its own.
urlpatterns = [
    path("admin/console/", admin.site.admin_view(views.console_home), name="admin_console_home"),
    path(
        "admin/console/teams/<int:team_id>/",
        admin.site.admin_view(views.team_detail),
        name="admin_console_team",
    ),
    path(
        "admin/console/teams/<int:team_id>/<slug:panel_key>/<slug:operation_key>/",
        admin.site.admin_view(views.run_team_operation),
        name="admin_console_team_operation",
    ),
    path(
        "admin/console/tools/<slug:tool_key>/",
        admin.site.admin_view(views.tool_page),
        name="admin_console_tool",
    ),
    # APPEND_SLASH is off, so a console URL typed without its trailing slash would fall through to the
    # Django admin catch-all.
    re_path(
        r"^admin/console(?P<rest>(?:/.*[^/])?)$",
        admin.site.admin_view(views.append_slash),
        name="admin_console_append_slash",
    ),
]
