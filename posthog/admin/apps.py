from functools import cached_property
from typing import Any

from django.contrib.admin import (
    AdminSite,
    actions as admin_actions,
)
from django.contrib.admin.apps import SimpleAdminConfig
from django.contrib.admin.sites import all_sites


class PostHogAdminSite(AdminSite):
    """AdminSite that lazily imports and registers every model admin on first
    `_registry` access. Importing all admins (and the models they pull in) is
    expensive and unnecessary for non-admin requests, so we defer it until the
    admin is actually visited.

    This replaces the `LazyAdminRegistry(dict)` monkeypatch that previously
    lived in `PostHogConfig.ready()`. Combined with `SimpleAdminConfig` (which
    skips Django's startup `autodiscover_modules('admin')` pass), all admin
    imports are deferred until first admin use.
    """

    def __init__(self, name: str = "admin") -> None:
        # Deliberately skip `AdminSite.__init__`'s `self._registry = {}`.
        # The cached_property below provides the registry on first access and
        # triggers `register_all_admin()` at that point.
        self.name = name
        self._actions = {"delete_selected": admin_actions.delete_selected}
        self._global_actions = self._actions.copy()
        all_sites.add(self)

    @cached_property
    def _registry(self) -> dict[Any, Any]:
        registry: dict[Any, Any] = {}
        # Pre-populate the cached_property's slot before calling
        # `register_all_admin()`. Inside that call, every
        # `admin.site.register(...)` reads `self._registry`; without the
        # pre-populated cache it would recurse back into this property.
        self.__dict__["_registry"] = registry
        from posthog.admin import register_all_admin

        register_all_admin()
        return registry


class PostHogAdminConfig(SimpleAdminConfig):
    """AppConfig for `django.contrib.admin` that:

    - Inherits from `SimpleAdminConfig` so Django does NOT run
      `autodiscover_modules('admin')` at startup. PostHog registers every
      model admin explicitly via `posthog.admin.register_all_admin()`, so
      autodiscover is dead weight that just imports admin modules eagerly.
    - Points `default_site` at `PostHogAdminSite` so `django.contrib.admin.site`
      becomes the lazy-registry instance described above.
    """

    default_site = "posthog.admin.apps.PostHogAdminSite"
