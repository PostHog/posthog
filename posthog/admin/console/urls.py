from django.contrib import admin
from django.urls import path

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
]
