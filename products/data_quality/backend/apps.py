"""Django app configuration for data_quality."""

from django.apps import AppConfig


class DataQualityConfig(AppConfig):
    name = "products.data_quality.backend"
    label = "data_quality"
    verbose_name = "Data quality"

    def ready(self) -> None:
        from . import activity_logging  # noqa: F401, PLC0415
