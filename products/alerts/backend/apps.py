from django.apps import AppConfig


class AlertsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.alerts.backend"
    label = "alerts"

    def ready(self) -> None:
        # Connect the alert activity-log and cleanup receivers (hog-function teardown,
        # subscription delete logging) at app-population. They used to wire in via the viewset
        # import; the lazy API router no longer pulls that, so connect here. They live in their
        # own module because the API module imports the alert detector stack (numpy) at module
        # scope — see activity_logging's docstring.
        from products.alerts.backend import activity_logging  # noqa: F401, PLC0415
