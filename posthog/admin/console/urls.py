import threading

from django.contrib import admin
from django.urls import URLPattern, URLResolver, path, re_path
from django.urls.resolvers import RoutePattern
from django.utils.datastructures import MultiValueDict
from django.utils.translation import get_language

import structlog

from posthog.admin.console import views
from posthog.admin.console.moved import MovedAction, MovedToConsole
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console

logger = structlog.get_logger(__name__)


def moved_url_patterns() -> list[URLPattern | URLResolver]:
    # Panels, tools and their console.py modules declare the old Django admin URLs they replaced, so a product
    # moves its own URLs without editing this file.
    patterns: list[URLPattern | URLResolver] = []
    for moved in console.moved():
        old_path = moved.old_path.removeprefix("admin/")
        if isinstance(moved, MovedAction):
            view = MovedToConsole.record_redirect(RECORD_TYPES[moved.record].plural, moved.target, moved.resolver)
            patterns.append(path(old_path, view))
        else:
            patterns.append(path(old_path, MovedToConsole.page_redirect(moved.title, moved.url)))
    return patterns


class MovedUrlResolver(URLResolver):
    """The old Django admin URLs that moved to the console, mounted under admin/.

    Building the routes imports every console contribution. That happens on the first request under admin/, not
    when the URLconf loads, so a contribution that raises breaks only these redirects, not every URL of the app.
    A failed build logs the error and serves no moved routes, and the next request under admin/ tries again.
    """

    def __init__(self) -> None:
        super().__init__(RoutePattern("admin/"), urlconf_name=[])
        self._moved_patterns: list[URLPattern | URLResolver] | None = None
        self._build_lock = threading.RLock()

    @property
    def url_patterns(self) -> list[URLPattern | URLResolver]:
        with self._build_lock:
            if self._moved_patterns is None:
                try:
                    self._moved_patterns = moved_url_patterns()
                except Exception:
                    logger.exception("admin_console_moved_urls_failed")
                    return []
            return self._moved_patterns

    def _populate(self) -> None:
        # Moved routes have no URL names, so reverse() has nothing to find here. Skipping them keeps every process
        # that calls reverse() from importing the console contributions.
        language_code = get_language()
        self._reverse_dict[language_code] = MultiValueDict()
        self._namespace_dict[language_code] = {}  # type: ignore[attr-defined]
        self._app_dict[language_code] = {}  # type: ignore[attr-defined]
        self._populated = True


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
        "admin/console/tools/<slug:tool_key>/<slug:operation_key>/",
        admin.site.admin_view(views.run_tool_operation),
        name="admin_console_tool_operation",
    ),
    MovedUrlResolver(),
    # APPEND_SLASH is off, so a console URL typed without its trailing slash would fall through to the
    # Django admin catch-all.
    re_path(
        r"^admin/console(?P<rest>(?:/.*[^/])?)$",
        admin.site.admin_view(views.append_slash),
        name="admin_console_append_slash",
    ),
]
