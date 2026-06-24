"""Django app configuration for access_control."""

from django.apps import AppConfig


class AccessControlConfig(AppConfig):
    name = "products.access_control.backend"
    label = "access_control"

    def ready(self) -> None:
        # Import property_access_control so its @receiver handlers register at startup. They invalidate
        # the per-request restriction cache on PropertyAccessControl / membership / role writes. Django
        # receivers only connect when their module is imported, so wiring that import here — on the
        # django.setup() path — guarantees it in every process (web, celery, temporal, migrate, shell)
        # instead of relying on some other module importing it incidentally.
        from products.access_control.backend import property_access_control  # noqa: F401, PLC0415
