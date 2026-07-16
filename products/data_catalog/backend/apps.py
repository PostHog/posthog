"""Django app configuration for data_catalog."""

from django.apps import AppConfig


class DataCatalogConfig(AppConfig):
    name = "products.data_catalog.backend"
    label = "data_catalog"
    verbose_name = "Data catalog"

    def ready(self) -> None:
        # noqa: PLC0415 — deferred to app-ready time so importing the signal receiver (which imports
        # models) doesn't run during django.setup().
        from . import activity_logging  # noqa: F401, PLC0415
