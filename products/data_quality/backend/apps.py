"""Django app configuration for data_quality."""

from django.apps import AppConfig


class DataQualityConfig(AppConfig):
    name = "products.data_quality.backend"
    label = "data_quality"
    verbose_name = "Data quality"

    def ready(self) -> None:
        from products.warehouse_sources.backend.facade.hooks import register_data_quality_checks_gate  # noqa: PLC0415

        from . import activity_logging  # noqa: F401, PLC0415
        from .logic.triggers import source_sync_checks_needed  # noqa: PLC0415

        register_data_quality_checks_gate(source_sync_checks_needed)
