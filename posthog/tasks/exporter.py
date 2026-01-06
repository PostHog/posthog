from time import perf_counter
from typing import Optional

from django.db import OperationalError, transaction

import structlog
import posthoganalytics
from celery import current_task, shared_task
from prometheus_client import Counter, Histogram
from urllib3.exceptions import MaxRetryError, ProtocolError

from posthog.hogql.errors import (
    QueryError,
    SyntaxError as HogQLSyntaxError,
)

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.errors import (
    CHQueryErrorIllegalAggregation,
    CHQueryErrorIllegalTypeOfArgument,
    CHQueryErrorNoCommonType,
    CHQueryErrorNotAnAggregate,
    CHQueryErrorS3Error,
    CHQueryErrorTooManySimultaneousQueries,
    CHQueryErrorTypeMismatch,
    CHQueryErrorUnknownFunction,
)
from posthog.event_usage import groups
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut
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

EXCEPTIONS_TO_RETRY = (
    CHQueryErrorS3Error,
    CHQueryErrorTooManySimultaneousQueries,
    OperationalError,
    ProtocolError,
    ConcurrencyLimitExceeded,
    MaxRetryError,  # This is from urllib, e.g. HTTP retries instead of "job retries"
    ClickHouseAtCapacity,
)

USER_QUERY_ERRORS = (
    QueryError,
    HogQLSyntaxError,
    ClickHouseQueryMemoryLimitExceeded,  # Users should reduce the date range on their query (or materialise)
    ClickHouseQueryTimeOut,  # Users should switch to materialised queries if they run into this
    CHQueryErrorIllegalTypeOfArgument,
    CHQueryErrorNoCommonType,
    CHQueryErrorNotAnAggregate,
    CHQueryErrorUnknownFunction,
    CHQueryErrorTypeMismatch,
    CHQueryErrorIllegalAggregation,
)

# Intentionally uncategorized errors (neither retryable nor user errors):
# - CHQueryErrorUnsupportedMethod: Known to be caused by missing UDFs (infrastructure issue, but not retryable)
# These should be revisited as we gather more data on their root causes.

# User query error class names for checking exception_type field
USER_QUERY_ERROR_NAMES = frozenset(cls.__name__ for cls in USER_QUERY_ERRORS)


def is_user_query_error_type(exception_type: str | None) -> bool:
    """Check if an exception type is a user query error."""
    return exception_type in USER_QUERY_ERROR_NAMES


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
def export_asset(
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
    export_asset_direct(exported_asset, limit=limit, max_height_pixels=max_height_pixels)


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
            EXPORT_QUEUED_COUNTER.labels(type="csv").inc()
        else:
            image_exporter.export_image(exported_asset, max_height_pixels=max_height_pixels)
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
        exported_asset.exception = None
        exported_asset.exception_type = None
        exported_asset.save(update_fields=["exception", "exception_type"])
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

        if is_retriable:
            raise

        exported_asset.exception = str(e)
        exported_asset.exception_type = type(e).__name__
        exported_asset.save()
