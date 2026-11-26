from django.conf import settings

from posthog.api.routing import RouterRegistry

from products.batch_exports.backend.presentation.views import file_download
from products.batch_exports.backend.presentation.views.batch_export import backfills, exports, runs


def register_routes(routers: RouterRegistry) -> None:
    # No worker runs an export while batch exports are off, so the API is absent, not half working.
    if not settings.BATCH_EXPORTS_ENABLED:
        return

    batch_exports_router = routers.projects.register(
        r"batch_exports", exports.BatchExportViewSet, "project_batch_exports", ["team_id"]
    )

    routers.projects.register(
        r"file_download_batch_exports",
        file_download.FileDownloadBatchExportOnDemandViewSet,
        "project_file_download_batch_exports",
        ["team_id"],
    )

    batch_exports_router.register(
        r"runs", runs.BatchExportRunViewSet, "project_batch_export_runs", ["team_id", "batch_export_id"]
    )

    batch_exports_router.register(
        r"backfills",
        backfills.BatchExportBackfillViewSet,
        "project_batch_export_backfills",
        ["team_id", "batch_export_id"],
    )
