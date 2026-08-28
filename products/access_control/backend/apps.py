"""Django app configuration for access_control."""

from django.apps import AppConfig


class AccessControlConfig(AppConfig):
    name = "products.access_control.backend"
    label = "access_control"

    def ready(self) -> None:
        # Connect the restriction-cache invalidation receivers at app-population. They used to be
        # wired as a side effect of the HogQL printer importing this module at django.setup();
        # that import is now deferred to compile time, so the wiring must happen here or the
        # receivers connect in no process and cache invalidation silently stops.
        from products.access_control.backend import property_access_control  # noqa: F401, PLC0415
