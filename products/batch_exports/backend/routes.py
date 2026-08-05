from posthog.api.routing import RouterRegistry

from products.batch_exports.backend.api import (
    batch_export as batch_exports,
    file_download,
)


def register_routes(routers: RouterRegistry) -> None:
    batch_exports_router = routers.projects.register(
        r"batch_exports", batch_exports.BatchExportViewSet, "project_batch_exports", ["team_id"]
    )

    routers.projects.register(
        r"file_download_batch_exports",
        file_download.FileDownloadBatchExportOnDemandViewSet,
        "project_file_download_batch_exports",
        ["team_id"],
    )

    batch_exports_router.register(
        r"runs", batch_exports.BatchExportRunViewSet, "project_batch_export_runs", ["team_id", "batch_export_id"]
    )

    batch_exports_router.register(
        r"backfills",
        batch_exports.BatchExportBackfillViewSet,
        "project_batch_export_backfills",
        ["team_id", "batch_export_id"],
    )

    routers.organizations.register(
        r"batch_exports",
        batch_exports.BatchExportOrganizationViewSet,
        "batch_exports",
        ["organization_id"],
    )
