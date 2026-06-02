from django.apps import AppConfig


class AlertsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.alerts.backend"
    label = "alerts"

    def ready(self) -> None:
        # Connect the alert-cleanup receivers (hog-function teardown, subscription delete logging)
        # at app-population. They used to wire in via the viewset import; the lazy API router no
        # longer pulls that, so connect here. The module's heavy insight-serializer import is
        # deferred, so importing it at startup stays cheap.
        from products.alerts.backend.api import alert  # noqa: F401, PLC0415
