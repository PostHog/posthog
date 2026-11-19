"""Best-effort lifecycle telemetry for warehouse account-property syncs.

Every call emits one `warehouse_account_property_sync` product event and mirrors a few
low-cardinality SDK metrics. Telemetry never raises into the sync and never blocks it:
events go through `ph_background_capture()` because `ph_scoped_capture()` flushes
synchronously on every call, which stalls a long-lived Temporal worker. Metrics use the
SDK path because `OtelInstrumentFactory` binds a no-op meter on the worker deployments.

Call this from activities, not from workflow code. A call inside a workflow is dropped,
because a workflow replay would otherwise send the same event again.
"""

from __future__ import annotations

import re
import sys
import math
from collections.abc import Mapping
from typing import Final, Literal, get_args

import structlog
import posthoganalytics

from posthog.ph_client import ph_background_capture
from posthog.utils import get_instance_region

from products.customer_analytics.backend.models.custom_property_sync_run import SyncSegment

logger = structlog.get_logger(__name__)

ACCOUNT_PROPERTY_SYNC_EVENT: Final = "warehouse_account_property_sync"

AccountPropertySyncPath = Literal["legacy", "fanout"]
AccountPropertySyncScope = Literal["attempt", "segment"]
AccountPropertySyncStatus = Literal["started", "completed", "failed", "cancelled"]

ATTEMPTS_METRIC: Final = "customer_analytics.account_property_sync.attempts"
SEGMENTS_METRIC: Final = "customer_analytics.account_property_sync.segments"
ATTEMPT_DURATION_METRIC: Final = "customer_analytics.account_property_sync.attempt.duration"
SEGMENT_DURATION_METRIC: Final = "customer_analytics.account_property_sync.segment.duration"
SEGMENT_SOURCES_METRIC: Final = "customer_analytics.account_property_sync.segment.sources"
ROWS_METRIC: Final = "customer_analytics.account_property_sync.rows"
SOURCE_ERRORS_METRIC: Final = "customer_analytics.account_property_sync.source_errors"

_PATHS: Final = frozenset(get_args(AccountPropertySyncPath))
_SCOPES: Final = frozenset(get_args(AccountPropertySyncScope))
_STATUSES: Final = frozenset(get_args(AccountPropertySyncStatus))
_TERMINAL_STATUSES: Final = frozenset({"completed", "failed", "cancelled"})
_SEGMENTS: Final = frozenset(SyncSegment.values)
_UNKNOWN_SEGMENT: Final = "unknown"

# Maps the counter keys that the sync returns to (event property, metric `kind` attribute).
# Any other key is dropped, so a future counter can't leak an unreviewed value into telemetry.
_ROW_COUNTERS: Final[Mapping[str, tuple[str, str]]] = {
    "rows_read": ("rows_read", "read"),
    "changed": ("rows_changed", "changed"),
    "matched": ("rows_matched", "matched"),
    "written": ("rows_written", "written"),
}
_SOURCE_ERRORS_COUNTER: Final = "source_errors"

# An exception class name, optionally module-qualified. Anything else (for example
# `str(error)`) can carry customer values, so it is replaced instead of sent.
_ERROR_TYPE_PATTERN: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,127}")
_INVALID_ERROR_TYPE: Final = "invalid"


def capture_account_property_sync_event(
    *,
    team_id: int,
    saved_query_id: str,
    job_id: str,
    segment: str,
    path: AccountPropertySyncPath,
    scope: AccountPropertySyncScope,
    status: AccountPropertySyncStatus,
    source_id: str | None = None,
    duration_seconds: float | None = None,
    attempt: int | None = None,
    source_count: int | None = None,
    counts: Mapping[str, int] | None = None,
    error_type: str | None = None,
    workflow_id: str | None = None,
    workflow_run_id: str | None = None,
) -> None:
    if path not in _PATHS or scope not in _SCOPES or status not in _STATUSES:
        # Log the field names only. The rejected values come from callers and stay out of logs.
        logger.warning(
            "account_property_sync_event_rejected",
            path_valid=path in _PATHS,
            scope_valid=scope in _SCOPES,
            status_valid=status in _STATUSES,
        )
        return
    try:
        if _in_workflow():
            return
        normalized_segment = str(segment) if str(segment) in _SEGMENTS else _UNKNOWN_SEGMENT
        valid_duration = _non_negative_float(duration_seconds)
        valid_attempt = _non_negative_int(attempt) or None
        valid_source_count = _non_negative_int(source_count)
        valid_counts = _valid_counts(counts)
    except Exception as error:
        logger.warning("account_property_sync_event_rejected", error_type=type(error).__name__)
        return

    try:
        properties: dict[str, object] = {
            "$process_person_profile": False,
            "team_id": int(team_id),
            "region": get_instance_region() or "unknown",
            "saved_query_id": str(saved_query_id),
            "job_id": str(job_id),
            "segment": normalized_segment,
            "path": path,
            "scope": scope,
            "status": status,
        }
        optional_properties: dict[str, object | None] = {
            "source_id": None if source_id is None else str(source_id),
            "attempt": valid_attempt,
            "is_retry": None if valid_attempt is None else valid_attempt > 1,
            "source_count": valid_source_count,
            "duration_seconds": valid_duration,
            "error_type": _safe_error_type(error_type),
            "workflow_id": None if workflow_id is None else str(workflow_id),
            "workflow_run_id": None if workflow_run_id is None else str(workflow_run_id),
        }
        properties.update({key: value for key, value in optional_properties.items() if value is not None})
        for counter, (event_property, _kind) in _ROW_COUNTERS.items():
            if counter in valid_counts:
                properties[event_property] = valid_counts[counter]
        if _SOURCE_ERRORS_COUNTER in valid_counts:
            properties["source_errors"] = valid_counts[_SOURCE_ERRORS_COUNTER]

        ph_background_capture()(
            distinct_id=f"warehouse_account_property_sync_team_{int(team_id)}",
            event=ACCOUNT_PROPERTY_SYNC_EVENT,
            properties=properties,
        )
    except Exception as error:
        # No exc_info: a traceback can render locals, and those include the caller's IDs and counts.
        logger.warning("account_property_sync_event_capture_failed", error_type=type(error).__name__)

    try:
        _record_metrics(
            attributes={"path": path, "segment": normalized_segment, "status": status},
            scope=scope,
            attempt=valid_attempt,
            duration_seconds=valid_duration,
            source_count=valid_source_count,
            counts=valid_counts,
        )
    except Exception as error:
        logger.warning("account_property_sync_metrics_failed", error_type=type(error).__name__)


def _record_metrics(
    *,
    attributes: dict[str, str],
    scope: AccountPropertySyncScope,
    attempt: int | None,
    duration_seconds: float | None,
    source_count: int | None,
    counts: Mapping[str, int],
) -> None:
    client = posthoganalytics.default_client
    metrics = getattr(client, "metrics", None) if client is not None else None
    if metrics is None:
        return
    terminal = attributes["status"] in _TERMINAL_STATUSES

    if scope == "segment":
        metrics.count(SEGMENTS_METRIC, 1, unit="{segment}", attributes=dict(attributes))
        if terminal and duration_seconds is not None:
            metrics.histogram(SEGMENT_DURATION_METRIC, duration_seconds, unit="s", attributes=dict(attributes))
        if terminal and source_count is not None:
            metrics.histogram(SEGMENT_SOURCES_METRIC, source_count, unit="{source}", attributes=dict(attributes))
        return

    is_retry = "unknown" if attempt is None else str(attempt > 1).lower()
    metrics.count(ATTEMPTS_METRIC, 1, unit="{attempt}", attributes={**attributes, "is_retry": is_retry})
    if not terminal:
        return
    if duration_seconds is not None:
        metrics.histogram(ATTEMPT_DURATION_METRIC, duration_seconds, unit="s", attributes=dict(attributes))
    # Row counters come from attempts only. Segment events may carry the summed counts of
    # the same attempts, so counting both scopes would double the totals.
    for counter, (_event_property, kind) in _ROW_COUNTERS.items():
        if counter in counts:
            metrics.count(ROWS_METRIC, counts[counter], unit="{row}", attributes={**attributes, "kind": kind})
    if _SOURCE_ERRORS_COUNTER in counts:
        metrics.count(
            SOURCE_ERRORS_METRIC, counts[_SOURCE_ERRORS_COUNTER], unit="{source}", attributes=dict(attributes)
        )


def _in_workflow() -> bool:
    # Being in a workflow implies temporalio is already imported, so this check keeps the
    # Temporal SDK off the import path of web and Celery callers.
    if "temporalio" not in sys.modules:
        return False

    from temporalio import workflow  # noqa: PLC0415 to keep the Temporal SDK off non-worker import paths

    return workflow.in_workflow()


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _non_negative_float(value: object) -> float | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _valid_counts(counts: Mapping[str, int] | None) -> dict[str, int]:
    if not counts:
        return {}
    allowed = (*_ROW_COUNTERS, _SOURCE_ERRORS_COUNTER)
    valid: dict[str, int] = {}
    for key in allowed:
        value = _non_negative_int(counts.get(key))
        if value is not None:
            valid[key] = value
    return valid


def _safe_error_type(error_type: str | None) -> str | None:
    if error_type is None:
        return None
    return error_type if _ERROR_TYPE_PATTERN.fullmatch(error_type) else _INVALID_ERROR_TYPE
