from typing import Optional

from celery import shared_task
from prometheus_client import Counter, Histogram

from django.db import transaction

from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.models import ExportedAsset
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.tasks.utils import CeleryQueue

EXPORT_QUEUED_COUNTER = Counter(
    "exporter_task_queued",
    "An export task was queued",
    labelnames=["type"],
)
EXPORT_SUCCEEDED_COUNTER = Counter(
    "exporter_task_succeeded",
    "An export task succeeded",
    labelnames=["type"],
)
EXPORT_ASSET_UNKNOWN_COUNTER = Counter(
    "exporter_task_unknown_asset",
    "An export task was for an unknown asset",
    labelnames=["type"],
)
EXPORT_FAILED_COUNTER = Counter(
    "exporter_task_failed",
    "An export task failed",
    labelnames=["type"],
)
EXPORT_TIMER = Histogram(
    "exporter_task_duration_seconds",
    "Time spent exporting an asset",
    labelnames=["type"],
    buckets=(1, 5, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, float("inf")),
)


# export_asset is used in chords/groups and so must not ignore its results
@shared_task(
    acks_late=True,
    ignore_result=False,
    # we let the hogql query run for HOGQL_INCREASED_MAX_EXECUTION_TIME, give this some breathing room
    # soft time limit throws an error and lets us clean up
    # hard time limit kills without a word
    soft_time_limit=HOGQL_INCREASED_MAX_EXECUTION_TIME + 60,
    time_limit=HOGQL_INCREASED_MAX_EXECUTION_TIME + 120,
    queue=CeleryQueue.EXPORTS.value,
    autoretry_for=(CHQueryErrorTooManySimultaneousQueries,),
    retry_backoff=1,
    retry_backoff_max=3,
    max_retries=3,
)
@transaction.atomic
def export_asset(exported_asset_id: int, limit: Optional[int] = None) -> None:
    from posthog.tasks.exports import csv_exporter, image_exporter

    # if Celery is lagging then you can end up with an exported asset that has had a TTL added
    # and that TTL has passed, in the exporter we don't care about that.
    # the TTL is for later cleanup.
    exported_asset: ExportedAsset = ExportedAsset.objects_including_ttl_deleted.select_for_update().get(
        pk=exported_asset_id
    )

    if exported_asset.export_format in (ExportedAsset.ExportFormat.CSV, ExportedAsset.ExportFormat.XLSX):
        csv_exporter.export_tabular(exported_asset, limit=limit)
        EXPORT_QUEUED_COUNTER.labels(type="csv").inc()
    else:
        image_exporter.export_image(exported_asset)
        EXPORT_QUEUED_COUNTER.labels(type="image").inc()
