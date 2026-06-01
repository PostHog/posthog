from typing import TYPE_CHECKING, Any

# The API route aggregator (the DRF router build + ~200 viewset imports) lives in
# `posthog.api.rest_router`. It is imported lazily — only when one of the router objects
# below is first accessed, which happens when the URLconf resolves (i.e. on the first web
# request). This keeps `import posthog.api.<submodule>` cheap: a plain `django.setup()`
# (shell, migrate, celery, CI) no longer builds 160 routes or drags every product's views
# (and the AI core) onto the startup path. See posthog/api/rest_router.py.
_ROUTER_EXPORTS = frozenset(
    {
        "router",
        "routers",
        "projects_router",
        "environments_router",
        "organizations_router",
        "legacy_project_dashboards_router",
        "environment_dashboards_router",
        "register_legacy_dual_route_team_nested_viewset",
        "api_not_found",
        # Re-exported view modules the root URLconf pulls from here (not submodules of this package).
        "hog_flow",
        "hog_flow_template",
        "hog_function_template",
    }
)


def __getattr__(name: str) -> Any:
    if name in _ROUTER_EXPORTS:
        from posthog.api import rest_router  # noqa: PLC0415

        return getattr(rest_router, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    from posthog.api.rest_router import (
        api_not_found as api_not_found,
        environment_dashboards_router as environment_dashboards_router,
        environments_router as environments_router,
        hog_flow as hog_flow,
        hog_flow_template as hog_flow_template,
        hog_function_template as hog_function_template,
        legacy_project_dashboards_router as legacy_project_dashboards_router,
        organizations_router as organizations_router,
        projects_router as projects_router,
        register_legacy_dual_route_team_nested_viewset as register_legacy_dual_route_team_nested_viewset,
        router as router,
        routers as routers,
    )
