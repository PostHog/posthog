from django.urls import include, path, re_path

from .api import hooks, license


def extend_api_router(router):
    router.register(r"license", license.LicenseViewSet)
    router.register(r"hooks", hooks.HookViewSet, basename="hooks")
