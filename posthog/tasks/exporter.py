from time import perf_counter
from typing import Optional

from django.db import transaction

import structlog
import posthoganalytics
from celery import current_task, shared_task
from prometheus_client import Counter, Histogram

from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.event_usage import groups
from posthog.models import ExportedAsset
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

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

EXCEPTIONS_TO_RETRY = (CHQueryErrorTooManySimultaneousQueries,)


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
    autoretry_for=EXCEPTIONS_TO_RETRY,
    retry_backoff=2,
    retry_backoff_max=3,
    max_retries=3,
)
@transaction.atomic
def export_asset(exported_asset_id: int, limit: Optional[int] = None) -> None:
    # if Celery is lagging then you can end up with an exported asset that has had a TTL added
    # and that TTL has passed, in the exporter we don't care about that.
    # the TTL is for later cleanup.
    exported_asset: ExportedAsset = ExportedAsset.objects_including_ttl_deleted.select_related(
        "created_by", "team", "team__organization"
    ).get(pk=exported_asset_id)
    export_asset_direct(exported_asset, limit)


def export_asset_direct(exported_asset: ExportedAsset, limit: Optional[int] = None) -> None:
    from posthog.tasks.exports import csv_exporter, image_exporter

    start_time = perf_counter()
    team = exported_asset.team
    distinct_id = exported_asset.created_by.distinct_id if exported_asset.created_by else str(team.uuid)
    analytics_props = {
        **exported_asset.get_analytics_metadata(),
        "task_id": current_task.request.id
        if current_task and current_task.request and current_task.request.id
        else None,
    }

    logger.info(
        "export_asset.starting",
        exported_asset_id=exported_asset.id,
        team_id=team.id,
    )

    from posthog.clickhouse.query_tagging import tag_queries

    tag_queries(exported_asset_id=exported_asset.id, export_format=exported_asset.export_format)

    posthoganalytics.capture(
        distinct_id=distinct_id,
        event="export started",
        properties=analytics_props,
        groups=groups(team.organization, team),
    )

    try:
        if exported_asset.export_format in (ExportedAsset.ExportFormat.CSV, ExportedAsset.ExportFormat.XLSX):
            csv_exporter.export_tabular(exported_asset, limit=limit)
            EXPORT_QUEUED_COUNTER.labels(type="csv").inc()
        else:
            image_exporter.export_image(exported_asset, max_height_pixels=limit)
            EXPORT_QUEUED_COUNTER.labels(type="image").inc()

        logger.info(
            "export_asset.succeeded",
            exported_asset_id=exported_asset.id,
            team_id=team.id,
        )
        posthoganalytics.capture(
            distinct_id=distinct_id,
            event="export succeeded",
            properties={
                **analytics_props,
                "duration_ms": round((perf_counter() - start_time) * 1000, 2),
            },
            groups=groups(team.organization, team),
        )
    except Exception as e:
        is_retriable = isinstance(e, EXCEPTIONS_TO_RETRY)

        logger.exception(
            "export_asset.error",
            exported_asset_id=exported_asset.id,
            error=str(e),
            might_retry=is_retriable,
            team_id=team.id,
        )
        posthoganalytics.capture(
            distinct_id=distinct_id,
            event="export failed",
            properties={
                **analytics_props,
                "error": str(e),
                "might_retry": is_retriable,
                "duration_ms": round((perf_counter() - start_time) * 1000, 2),
            },
            groups=groups(team.organization, team),
        )

        if is_retriable:
            raise

        exported_asset.exception = str(e)
        exported_asset.save()
