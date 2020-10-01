from posthog.api import OptionalTrailingSlashRouter

from .api import hooks, license


def extend_api_router(router: OptionalTrailingSlashRouter):
    router.register(r"license", license.LicenseViewSet)
    router.register(r"hooks", hooks.HookViewSet, basename="hooks")
