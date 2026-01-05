from time import perf_counter
from typing import Optional

from django.db import transaction

import structlog
import posthoganalytics
from celery import current_task, shared_task
from prometheus_client import Counter, Histogram

from posthog.event_usage import groups
from posthog.models import ExportedAsset
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.tasks.exports.failure_handler import EXCEPTIONS_TO_RETRY, USER_QUERY_ERRORS, classify_failure_type
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)

EXPORT_SUCCEEDED_COUNTER = Counter(
    "exporter_task_succeeded",
    "An export task succeeded",
    labelnames=["type"],
)
EXPORT_FAILED_COUNTER = Counter(
    "exporter_task_failed",
    "An export task failed",
    labelnames=["type", "failure_type"],
)
EXPORT_TIMER = Histogram(
    "exporter_task_duration_seconds",
    "Time spent exporting an asset",
    labelnames=["type"],
    buckets=(1, 5, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, float("inf")),
)


def record_export_failure(exported_asset: ExportedAsset, e: Exception) -> None:
    failure_type = classify_failure_type(e)
    exported_asset.exception = str(e)
    exported_asset.exception_type = type(e).__name__
    exported_asset.failure_type = failure_type
    exported_asset.save(update_fields=["exception", "exception_type", "failure_type"])
    EXPORT_FAILED_COUNTER.labels(type=exported_asset.export_format, failure_type=failure_type).inc()


def _is_final_export_attempt(exception: Exception, current_retries: int, max_retries: int) -> bool:
    is_retriable = isinstance(exception, EXCEPTIONS_TO_RETRY)
    return not is_retriable or current_retries >= max_retries


# export_asset is used in chords/groups and so must not ignore its results
@shared_task(
    bind=True,
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
def export_asset(
    self,
    exported_asset_id: int,
    limit: Optional[int] = None,  # For CSV/XLSX: max row count
    max_height_pixels: Optional[int] = None,  # For images: max screenshot height in pixels
) -> None:
    # if Celery is lagging then you can end up with an exported asset that has had a TTL added
    # and that TTL has passed, in the exporter we don't care about that.
    # the TTL is for later cleanup.
    exported_asset: ExportedAsset = ExportedAsset.objects_including_ttl_deleted.select_related(
        "created_by", "team", "team__organization"
    ).get(pk=exported_asset_id)

    try:
        with transaction.atomic():
            export_asset_direct(exported_asset, limit=limit, max_height_pixels=max_height_pixels)
    except Exception as e:
        # Failure recording must happen OUTSIDE the atomic block so it persists after rollback
        if _is_final_export_attempt(e, self.request.retries, self.max_retries):
            record_export_failure(exported_asset, e)
        raise


def export_asset_direct(
    exported_asset: ExportedAsset,
    limit: Optional[int] = None,  # For CSV/XLSX: max row count
    max_height_pixels: Optional[int] = None,  # For images: max screenshot height in pixels
) -> None:
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
        else:
            image_exporter.export_image(exported_asset, max_height_pixels=max_height_pixels)
        EXPORT_SUCCEEDED_COUNTER.labels(type=exported_asset.export_format).inc()

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
        exported_asset.exception = None
        exported_asset.exception_type = None
        exported_asset.failure_type = None
        exported_asset.save(update_fields=["exception", "exception_type", "failure_type"])
    except Exception as e:
        is_retriable = isinstance(e, EXCEPTIONS_TO_RETRY)
        is_user_error = isinstance(e, USER_QUERY_ERRORS)

        if is_user_error:
            logger.warning(
                "export_asset.user_config_error",
                exported_asset_id=exported_asset.id,
                error=str(e),
                team_id=team.id,
            )
        else:
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
                "is_user_error": is_user_error,
                "duration_ms": round((perf_counter() - start_time) * 1000, 2),
            },
            groups=groups(team.organization, team),
        )

        raise
