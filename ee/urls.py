from django.urls import include, path, re_path

from ee.clickhouse import models

from .api import license as _license


def extend_api_router(router):
    router.register(r"license", _license.LicenseViewSet)
