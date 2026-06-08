"""Django app configuration for batch_exports."""

from django.apps import AppConfig


class BatchExportsConfig(AppConfig):
    name = "products.batch_exports.backend"
    label = "batch_exports"

    def ready(self) -> None:
        # batch_export.py holds the BatchExport activity-log receiver (handle_batch_export_change),
        # which used to wire in via the viewset import. The lazy API router no longer pulls that, and
        # the Temporal batch-export service mutates BatchExport directly (pause/unpause), so without
        # wiring here its audit-log entries are silently dropped in the worker. The module is light
        # (its only heavy import, the batch-export Temporal framework, is deferred).
        from products.batch_exports.backend.api import batch_export  # noqa: F401, PLC0415
