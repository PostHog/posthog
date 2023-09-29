from typing import Optional

from prometheus_client import Counter, Histogram

from posthog.celery import app
from posthog.models import ExportedAsset

EXPORT_QUEUED_COUNTER = Counter(
    "exporter_task_queued",
    "An export task was queued",
    labelnames=["type"],
)
EXPORT_SUCCEEDED_COUNTER = Counter(
    "exporter_task_csv_succeeded",
    "A CSV export task succeeded",
    labelnames=["type"],
)
EXPORT_ASSET_UNKNOWN_COUNTER = Counter(
    "exporter_task_csv_unknown_asset",
    "A CSV export task was for an unknown asset",
    labelnames=["type"],
)
EXPORT_FAILED_COUNTER = Counter(
    "exporter_task_csv_failed",
    "A CSV export task failed",
    labelnames=["type"],
)
EXPORT_TIMER = Histogram(
    "exporter_task_csv_duration_seconds",
    "Time spent exporting an asset",
    labelnames=["type"],
)


@app.task(autoretry_for=(Exception,), max_retries=5, retry_backoff=True, acks_late=True)
def export_asset(exported_asset_id: int, limit: Optional[int] = None) -> None:
    from posthog.tasks.exports import csv_exporter, image_exporter

    # if Celery is lagging then you can end up with an exported asset that has had a TTL added
    # and that TTL has passed, in the exporter we don't care about that.
    # the TTL is for later cleanup.
    exported_asset: ExportedAsset = ExportedAsset.objects_including_ttl_deleted.select_related(
        "insight", "dashboard"
    ).get(pk=exported_asset_id)

    is_csv_export = exported_asset.export_format == ExportedAsset.ExportFormat.CSV
    if is_csv_export:
        max_limit = exported_asset.export_context.get("max_limit", 10000)
        csv_exporter.export_csv(exported_asset, limit=limit, max_limit=max_limit)
        EXPORT_QUEUED_COUNTER.labels(type="csv").inc()
    else:
        image_exporter.export_image(exported_asset)
        EXPORT_QUEUED_COUNTER.labels(type="image").inc()
