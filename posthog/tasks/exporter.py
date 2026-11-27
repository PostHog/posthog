from collections.abc import Callable
from time import perf_counter
from typing import Any, Optional

import structlog
import posthoganalytics
from celery import current_task, shared_task
from prometheus_client import Counter, Histogram

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource, groups
from posthog.query_creator_access import CreatorLeftOrganizationError, assert_creator_can_run
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME
from posthog.tasks.utils import CeleryQueue

from products.exports.backend.facade.exporters import get_export_format_handler
from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.source_authentication import assert_export_authorization
from products.exports.backend.tasks.failure_handler import (
    FAILURE_TYPE_USER,
    InvalidExportContext,
    RetryableExportError,
    classify_failure_type,
)

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
BATCH_SESSION_TIMEOUT_MS = 600_000

EXPORT_TIMER = Histogram(
    "exporter_task_duration_seconds",
    "Time spent exporting an asset",
    labelnames=["type"],
    buckets=(1, 5, 10, 30, 60, 120, 240, 300, 360, 420, 480, 540, 600, float("inf")),
)


def _record_export_failure(exported_asset: ExportedAsset, e: Exception) -> None:
    failure_type = classify_failure_type(e)
    exported_asset.exception = str(e)
    exported_asset.exception_type = type(e).__name__
    exported_asset.failure_type = failure_type
    exported_asset.save(update_fields=["exception", "exception_type", "failure_type"])
    EXPORT_FAILED_COUNTER.labels(type=exported_asset.export_format, failure_type=failure_type).inc()


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
)
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

    # Retries are handled by Temporal at the activity level.
    # The Celery path is a legacy fallback until one-off exports are fully migrated.
    try:
        export_asset_direct(exported_asset, limit=limit, max_height_pixels=max_height_pixels)
    except Exception:
        # Swallow exceptions so that users see the exception message in the toast (without hovering over the failed
        # export icon).
        pass


@frozen
class _ExportRun:
    exported_asset: ExportedAsset
    source: EventSource
    distinct_id: str | None
    analytics_props: dict[str, Any]
    started_at: float


def _start_export(
    exported_asset: ExportedAsset, source: Optional[EventSource], extra_props: Optional[dict[str, Any]] = None
) -> _ExportRun:
    started_at = perf_counter()
    team = exported_asset.team
    distinct_id = exported_asset.created_by.distinct_id if exported_asset.created_by else str(team.uuid)
    analytics_props = {
        **exported_asset.get_analytics_metadata(),
        "task_id": current_task.request.id
        if current_task and current_task.request and current_task.request.id
        else None,
        **(extra_props or {}),
    }
    if source == EventSource.SUBSCRIPTION:
        analytics_props["$update_person_last_seen_at"] = False

    logger.info(
        "export_asset.starting",
        exported_asset_id=exported_asset.id,
        team_id=team.id,
        export_format=exported_asset.export_format,
    )

    from posthog.clickhouse.query_tagging import tag_queries

    tag_queries(exported_asset_id=exported_asset.id, export_format=exported_asset.export_format)

    posthoganalytics.capture(
        distinct_id=distinct_id,
        event="export started",
        properties=analytics_props,
        groups=groups(team.organization, team),
    )
    return _ExportRun(
        exported_asset=exported_asset,
        source=source or EventSource.EXPORT,
        distinct_id=distinct_id,
        analytics_props=analytics_props,
        started_at=started_at,
    )


def _authorize_export(run: _ExportRun) -> None:
    exported_asset = run.exported_asset
    if exported_asset.created_by is not None:
        assert_creator_can_run(
            exported_asset.created_by, exported_asset.team, exported_asset.dashboard, exported_asset.insight
        )
    elif run.source == EventSource.SUBSCRIPTION:
        # A subscription copies its owner onto every asset, so an ownerless one means the owner's account
        # was deleted. Other exports have no owner on purpose (logs, activity logs, sharing renders).
        raise CreatorLeftOrganizationError()
    assert_export_authorization(exported_asset)


def _finish_export(run: _ExportRun) -> None:
    exported_asset = run.exported_asset
    team = exported_asset.team
    EXPORT_SUCCEEDED_COUNTER.labels(type=exported_asset.export_format).inc()
    logger.info(
        "export_asset.succeeded",
        exported_asset_id=exported_asset.id,
        team_id=team.id,
    )
    posthoganalytics.capture(
        distinct_id=run.distinct_id,
        event="export succeeded",
        properties={
            **run.analytics_props,
            "duration_ms": round((perf_counter() - run.started_at) * 1000, 2),
        },
        groups=groups(team.organization, team),
    )
    exported_asset.exception = None
    exported_asset.exception_type = None
    exported_asset.failure_type = None
    exported_asset.save(update_fields=["exception", "exception_type", "failure_type"])


def _fail_export(run: _ExportRun, e: Exception) -> None:
    exported_asset = run.exported_asset
    team = exported_asset.team
    is_user_error = classify_failure_type(e) == FAILURE_TYPE_USER

    if is_user_error:
        logger.warning(
            "export_asset.user_config_error",
            exported_asset_id=exported_asset.id,
            error=str(e),
            team_id=team.id,
        )
    else:
        logger.exception(
            "export_asset.failed",
            exported_asset_id=exported_asset.id,
            error=str(e),
            team_id=team.id,
        )

    posthoganalytics.capture(
        distinct_id=run.distinct_id,
        event="export failed",
        properties={
            **run.analytics_props,
            "error": str(e),
            "is_user_error": is_user_error,
            "duration_ms": round((perf_counter() - run.started_at) * 1000, 2),
        },
        groups=groups(team.organization, team),
    )

    _record_export_failure(exported_asset, e)


def export_asset_direct(
    exported_asset: ExportedAsset,
    limit: Optional[int] = None,  # For CSV/XLSX: max row count
    max_height_pixels: Optional[int] = None,  # For images: max screenshot height in pixels
    source: Optional[EventSource] = None,  # EventSource value to tag queries with (e.g. "subscription")
) -> None:
    from products.exports.backend.tasks import csv_exporter, image_exporter

    run = _start_export(exported_asset, source)

    try:
        _authorize_export(run)
        export_handler = get_export_format_handler(
            export_format=exported_asset.export_format, kind=exported_asset.export_kind
        )
        if export_handler is not None:
            export_handler(exported_asset)
        elif exported_asset.export_format in (ExportedAsset.ExportFormat.CSV, ExportedAsset.ExportFormat.XLSX):
            csv_exporter.export_tabular(exported_asset, limit=limit, source=run.source)
        elif exported_asset.export_format == ExportedAsset.ExportFormat.JSONL:
            raise InvalidExportContext(
                "This export can't be generated. Contact support if this keeps happening.", reportable=True
            )
        else:
            image_exporter.export_image(exported_asset, max_height_pixels=max_height_pixels, source=run.source)
        _finish_export(run)
    except Exception as e:
        _fail_export(run, e)
        raise


def _stopped_before_render(exported_assets: list[ExportedAsset]) -> dict[int, Exception]:
    return {
        exported_asset.id: RetryableExportError("The batch stopped before this asset rendered")
        for exported_asset in exported_assets
    }


def export_image_assets_batched(
    exported_assets: list[ExportedAsset], source: Optional[EventSource], should_stop: Callable[[], bool]
) -> dict[int, Exception]:
    from products.exports.backend.tasks import image_exporter

    batch_props = {"render_mode": "batched", "render_batch_size": len(exported_assets)}
    errors: dict[int, Exception] = {}
    warmed: list[tuple[_ExportRun, dict[int, str]]] = []
    for index, exported_asset in enumerate(exported_assets):
        if should_stop():
            return {**errors, **_stopped_before_render(exported_assets[index:])}
        run = _start_export(exported_asset, source, batch_props)
        try:
            _authorize_export(run)
            insight_cache_keys = image_exporter.warm_image_export(exported_asset, source=run.source)
        except Exception as e:
            _fail_export(run, e)
            errors[exported_asset.id] = e
            continue
        warmed.append((run, insight_cache_keys))

    with image_exporter.BrowserlessRenderSession(
        session_timeout_ms=BATCH_SESSION_TIMEOUT_MS, mode="batched"
    ) as session:
        for index, (run, insight_cache_keys) in enumerate(warmed):
            if should_stop():
                errors.update(_stopped_before_render([unrendered.exported_asset for unrendered, _ in warmed[index:]]))
                break
            try:
                image_exporter.render_image_export(run.exported_asset, insight_cache_keys, session=session)
                _finish_export(run)
            except Exception as e:
                _fail_export(run, e)
                errors[run.exported_asset.id] = e

    return errors
