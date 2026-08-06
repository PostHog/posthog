"""Django app configuration for batch_exports."""

from django.apps import AppConfig


class BatchExportsConfig(AppConfig):
    name = "products.batch_exports.backend"
    label = "batch_exports"

    def ready(self) -> None:
        # The BatchExport activity-log receiver (handle_batch_export_change) used to wire in via the
        # viewset import. The lazy API router no longer pulls that, and the Temporal batch-export
        # service mutates BatchExport directly (pause/unpause), so without wiring here its audit-log
        # entries are silently dropped in the worker. It lives in its own module because the API
        # module is heavy (DRF, service layer, Temporal client) — see activity_logging's docstring.
        from products.batch_exports.backend import activity_logging  # noqa: F401, PLC0415
