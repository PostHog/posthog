from rest_framework_extensions.routers import NestedRegistryItem

from posthog.api.routing import DefaultRouterPlusPlus

from .api import debug_ch_queries, hooks, license


def extend_api_router(root_router: DefaultRouterPlusPlus, *, projects_router: NestedRegistryItem):
    root_router.register(r"license", license.LicenseViewSet)
    root_router.register(r"debug_ch_queries", debug_ch_queries.DebugCHQueries, "debug_ch_queries")
    projects_router.register(r"hooks", hooks.HookViewSet, "project_hooks", ["team_id"])
