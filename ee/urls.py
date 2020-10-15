from posthog.api import HedgeRouter

from .api import hooks, license


def extend_api_router(router: HedgeRouter):
    router.register(r"license", license.LicenseViewSet)
    router.register(r"hooks", hooks.HookViewSet, basename="hooks")
