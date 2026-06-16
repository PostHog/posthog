"""Django app configuration for access_control."""

from django.apps import AppConfig


class AccessControlConfig(AppConfig):
    name = "products.access_control.backend"
    label = "access_control"

    def ready(self) -> None:
        # Connect the property-access-control cache-invalidation receivers at app-population. They used
        # to wire in as an import side effect of the viewset module; the lazy API router no longer pulls
        # that, so a process that never builds the router (celery, temporal, migrate, shell) would stop
        # invalidating the restriction cache on ACL / membership / role writes. The module is import-light
        # (only models, constants, and celery signals — all already on the django.setup() path).
        from products.access_control.backend import property_access_control  # noqa: F401, PLC0415
