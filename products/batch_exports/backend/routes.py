from posthog.api.routing import RouterRegistry

from products.batch_exports.backend.presentation.views import file_download
from products.batch_exports.backend.presentation.views.batch_export import export_backfills, export_runs, exports


def register_routes(routers: RouterRegistry) -> None:
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
        r"runs", export_runs.BatchExportRunViewSet, "project_batch_export_runs", ["team_id", "batch_export_id"]
    )

    batch_exports_router.register(
        r"backfills",
        export_backfills.BatchExportBackfillViewSet,
        "project_batch_export_backfills",
        ["team_id", "batch_export_id"],
    )
