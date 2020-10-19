from posthog.api import DefaultRouterPlusPlus

from .api import hooks, license


def extend_api_router(router: DefaultRouterPlusPlus):
    router.register(r"license", license.LicenseViewSet)
    router.register(r"hooks", hooks.HookViewSet, basename="hooks")
