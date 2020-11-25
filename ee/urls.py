from rest_framework_extensions.routers import NestedRegistryItem

from posthog.api.routing import DefaultRouterPlusPlus

from .api import hooks, license


def extend_api_router(root_router: DefaultRouterPlusPlus, *, projects_router: NestedRegistryItem):
    root_router.register(r"license", license.LicenseViewSet)
    projects_router.register(r"hooks", hooks.HookViewSet, "project_hooks", ["team_id"])
