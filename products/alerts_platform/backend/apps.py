"""Django app configuration for alerts_platform."""

from django.apps import AppConfig


class AlertsPlatformConfig(AppConfig):
    name = "products.alerts_platform.backend"
    label = "alerts_platform"

    def ready(self) -> None:
        # Connects the activity-log receiver in every process, because checks, commands and the API
        # all write configurations.
        from products.alerts_platform.backend import activity_logging  # noqa: F401, PLC0415
