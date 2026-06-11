import importlib
import importlib.util
from typing import TYPE_CHECKING, Any

# The API route aggregator (the DRF router build + ~200 viewset imports) lives in
# `posthog.api.rest_router`, imported lazily — only when a name it defines or re-exports
# (the router objects, view modules like `dashboard`) is first accessed, which in practice
# is when the URLconf resolves (first web request). Real submodules (`posthog.api.monitoring`,
# `.file_system`, ...) resolve directly without building the aggregator, so a plain
# `django.setup()` (shell, migrate, celery, CI) stays cheap. See posthog/api/rest_router.py.


def __getattr__(name: str) -> Any:
    # A real submodule — import it directly, cheaply, without building the aggregator. This is
    # what keeps django.setup() off the route-building path (the setup-time importers all hit
    # real submodules).
    if importlib.util.find_spec(f"{__name__}.{name}") is not None:
        return importlib.import_module(f"{__name__}.{name}")
    # Otherwise it's a name the aggregator defines or re-exports (router objects, plus view
    # modules like `dashboard` that come from other packages). Build it lazily and delegate.
    from posthog.api import rest_router  # noqa: PLC0415

    try:
        return getattr(rest_router, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None


if TYPE_CHECKING:
    from posthog.api.rest_router import (
        api_not_found as api_not_found,
        environments_router as environments_router,
        organizations_router as organizations_router,
        projects_router as projects_router,
        register_legacy_dual_route_team_nested_viewset as register_legacy_dual_route_team_nested_viewset,
        router as router,
        routers as routers,
    )
