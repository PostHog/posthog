"""Django app configuration for data_tools."""

from django.apps import AppConfig


class DataToolsConfig(AppConfig):
    name = "products.data_tools.backend"
    label = "data_tools"

    def ready(self) -> None:
        # Deferred to app-ready time so importing the signal receiver (which imports
        # models) doesn't run during django.setup().
        from . import activity_logging  # noqa: F401, PLC0415
