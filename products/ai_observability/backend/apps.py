from collections.abc import Mapping
from typing import TYPE_CHECKING

from django.apps import AppConfig

if TYPE_CHECKING:
    from products.exports.backend.models.exported_asset import ExportedAsset


def _export_dataset_jsonl(asset: "ExportedAsset") -> None:
    from products.ai_observability.backend.dataset_export import (  # noqa: PLC0415 -- keeps dataset export dependencies off the Django startup path
        export_dataset_jsonl,
    )

    export_dataset_jsonl(asset)


def _dataset_export_content_path(*, team_id: int, asset_id: int, export_context: Mapping[str, object]) -> str | None:
    from products.ai_observability.backend.api.dataset_exports import (  # noqa: PLC0415 -- keeps the dataset API off the Django startup path
        dataset_export_content_path,
    )

    return dataset_export_content_path(team_id=team_id, asset_id=asset_id, export_context=export_context)


def _export_trace_json(asset: "ExportedAsset") -> None:
    from products.ai_observability.backend.tasks.trace_export import (  # noqa: PLC0415 -- keeps trace reads off the Django startup path
        export_trace_json,
    )

    export_trace_json(asset)


def _trace_export_content_path(*, team_id: int, asset_id: int, export_context: Mapping[str, object]) -> str | None:
    from products.ai_observability.backend.presentation.trace_exports import (  # noqa: PLC0415 -- keeps the trace API off the Django startup path
        trace_export_content_path,
    )

    return trace_export_content_path(team_id=team_id, asset_id=asset_id, export_context=export_context)


class AIObservabilityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "products.ai_observability.backend"
    label = "ai_observability"

    def ready(self) -> None:
        # Connect the Evaluation activity-log receiver at app-population. It lives in a light
        # activity_logging module (not the evaluations viewset, which pulls scipy / google.genai /
        # the ai_observability Temporal worker) so wiring it here stays off the django.setup() path.
        from products.ai_observability.backend import activity_logging  # noqa: F401, PLC0415
        from products.ai_observability.backend.logic.traces.trace_export import (  # noqa: PLC0415 -- registration belongs at app population
            TRACE_EXPORT_FORMAT,
            TRACE_EXPORT_KIND,
        )
        from products.exports.backend.facade.exporters import (  # noqa: PLC0415 -- registration belongs at app population
            DATASET_EXPORT_KIND,
            register_export_format_handler,
        )

        register_export_format_handler(
            export_format="application/x-ndjson",
            kind=DATASET_EXPORT_KIND,
            handler=_export_dataset_jsonl,
            content_path=_dataset_export_content_path,
        )
        register_export_format_handler(
            export_format=TRACE_EXPORT_FORMAT,
            kind=TRACE_EXPORT_KIND,
            handler=_export_trace_json,
            content_path=_trace_export_content_path,
        )
