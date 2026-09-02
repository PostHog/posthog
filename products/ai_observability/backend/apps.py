from typing import TYPE_CHECKING

from django.apps import AppConfig

if TYPE_CHECKING:
    from products.exports.backend.models.exported_asset import ExportedAsset


def _export_dataset_jsonl(asset: "ExportedAsset") -> None:
    from products.ai_observability.backend.dataset_export import (  # noqa: PLC0415 -- keeps dataset export dependencies off the Django startup path
        export_dataset_jsonl,
    )

    export_dataset_jsonl(asset)


class AIObservabilityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.ai_observability.backend"
    label = "ai_observability"

    def ready(self) -> None:
        # Connect the Evaluation activity-log receiver at app-population. It lives in a light
        # activity_logging module (not the evaluations viewset, which pulls scipy / google.genai /
        # the ai_observability Temporal worker) so wiring it here stays off the django.setup() path.
        from products.ai_observability.backend import activity_logging  # noqa: F401, PLC0415
        from products.exports.backend.facade.exporters import (  # noqa: PLC0415 -- registration belongs at app population
            register_export_format_handler,
        )

        register_export_format_handler("application/x-ndjson", _export_dataset_jsonl)
