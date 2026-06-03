"""Django app configuration for batch_exports."""

from django.apps import AppConfig


class BatchExportsConfig(AppConfig):
    name = "products.batch_exports.backend"
    label = "batch_exports"

    def ready(self) -> None:
        # Connect the batch-import activity-logging / delete receivers at app-population. They used
        # to wire in via the viewset import; the lazy API router no longer pulls that, so connect here.
        # The module's only heavy import (the batch-export Temporal framework) is deferred, so importing
        # it at startup stays cheap.
        # batch_export.py holds the BatchExport activity-log receiver (handle_batch_export_change).
        # The Temporal batch-export service mutates BatchExport directly (pause/unpause), so without
        # this its audit-log entries are silently dropped in the worker. The module is light.
        from products.batch_exports.backend.api import (
            batch_export,  # noqa: F401, PLC0415
            batch_imports,  # noqa: F401, PLC0415
        )
