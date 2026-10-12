from enum import StrEnum
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache

import structlog
from prometheus_client import Counter

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.exceptions_capture import capture_exception

from products.cdp.backend.facade.models import HogFunction
from products.warehouse_sources.backend.facade.api import get_sync_alert_context
from products.warehouse_sources.backend.facade.types import ExternalDataJobStatus, ExternalDataSchemaStatus

logger = structlog.get_logger(__name__)

SYNC_ALERT_EVENTS = Counter(
    "dwh_sync_alert_events_total",
    "Sync alert internal events, by event name and outcome",
    labelnames=["event", "outcome"],
)

MAX_ERROR_LENGTH = 1000

# A destination created less than this long ago can miss a completed sync. The check runs on every
# completed run of every schema, so it must not query Postgres each time.
SUBSCRIBER_CACHE_SECONDS = 60


class SyncAlertEvent(StrEnum):
    """Internal events a destination can subscribe to. Saved destinations filter on these names."""

    FAILED = "$data_warehouse_sync_failed"
    RECOVERED = "$data_warehouse_sync_recovered"
    COMPLETED = "$data_warehouse_sync_completed"
    BILLING_LIMIT_REACHED = "$data_warehouse_billing_limit_reached"


class SyncAlertKind(StrEnum):
    JOB_FAILED = "job_failed"
    SCHEMA_PAUSED = "schema_paused"
    CDC_BROKEN = "cdc_broken"
    BILLING_LIMIT_REACHED = "reached"
    BILLING_LIMIT_TOO_LOW = "too_low"


BILLING_KIND_BY_STATUS: dict[str, SyncAlertKind] = {
    ExternalDataSchemaStatus.BILLING_LIMIT_REACHED: SyncAlertKind.BILLING_LIMIT_REACHED,
    ExternalDataSchemaStatus.BILLING_LIMIT_TOO_LOW: SyncAlertKind.BILLING_LIMIT_TOO_LOW,
}

# Events that fire on every run. The others fire on a state change, so their volume is low enough
# to produce without a subscriber check.
EVENTS_PRODUCED_ONLY_FOR_SUBSCRIBERS = frozenset({SyncAlertEvent.COMPLETED})


def events_for_terminal_run(
    *,
    status: ExternalDataJobStatus,
    previous_schema_status: str | None,
    previous_failed_runs: int,
    counts_as_source_failure: bool,
) -> list[SyncAlertEvent]:
    """The alert events for the first terminal write of a run.

    Failed, recovered and billing events fire on a state change of the schema, so a schema that
    fails each retry sends one alert, not one for each run. `previous_failed_runs` is the failure
    streak before this run moved it. A failure that says nothing about the source does not start
    a streak, so it sends no failed alert and its next completed run sends no recovered alert.
    """
    if status == ExternalDataJobStatus.FAILED:
        return [SyncAlertEvent.FAILED] if counts_as_source_failure and previous_failed_runs == 0 else []

    if status == ExternalDataJobStatus.COMPLETED:
        recovered = previous_failed_runs > 0 or previous_schema_status in BILLING_KIND_BY_STATUS
        return [SyncAlertEvent.RECOVERED, SyncAlertEvent.COMPLETED] if recovered else [SyncAlertEvent.COMPLETED]

    if status in BILLING_KIND_BY_STATUS and previous_schema_status != status:
        return [SyncAlertEvent.BILLING_LIMIT_REACHED]

    return []


def emit_terminal_run_alerts(
    *,
    team_id: int,
    schema_id: str,
    job_id: str,
    status: ExternalDataJobStatus,
    previous_schema_status: str | None,
    previous_failed_runs: int,
    counts_as_source_failure: bool,
) -> None:
    for event in events_for_terminal_run(
        status=status,
        previous_schema_status=previous_schema_status,
        previous_failed_runs=previous_failed_runs,
        counts_as_source_failure=counts_as_source_failure,
    ):
        kind = SyncAlertKind.JOB_FAILED if event == SyncAlertEvent.FAILED else BILLING_KIND_BY_STATUS.get(status)
        emit_sync_alert(team_id=team_id, schema_id=schema_id, event=event, kind=kind, job_id=job_id)


def emit_sync_alert(
    *,
    team_id: int,
    schema_id: str,
    event: SyncAlertEvent,
    kind: SyncAlertKind | None = None,
    job_id: str | None = None,
) -> None:
    """Produce one sync alert event. Never raises, because an alert must not fail the sync that sent it."""
    try:
        if event in EVENTS_PRODUCED_ONLY_FOR_SUBSCRIBERS and not _has_subscriber(team_id, event):
            SYNC_ALERT_EVENTS.labels(event=event.value, outcome="no_subscriber").inc()
            return

        properties = _build_properties(team_id=team_id, schema_id=schema_id, event=event, kind=kind, job_id=job_id)
        if properties is None:
            SYNC_ALERT_EVENTS.labels(event=event.value, outcome="schema_missing").inc()
            return

        produce_internal_event(
            team_id=team_id,
            event=InternalEventEvent(event=event.value, distinct_id=f"team_{team_id}", properties=properties),
        )
        SYNC_ALERT_EVENTS.labels(event=event.value, outcome="produced").inc()
    except Exception as error:
        SYNC_ALERT_EVENTS.labels(event=event.value, outcome="error").inc()
        logger.exception("dwh_sync_alert_emit_failed", team_id=team_id, schema_id=schema_id, event_name=event.value)
        capture_exception(error)


def _has_subscriber(team_id: int, event: SyncAlertEvent) -> bool:
    cache_key = f"dwh_sync_alert_subscriber:{team_id}:{event.value}"
    cached = cache.get(cache_key)
    if cached is not None:
        return bool(cached)

    has_subscriber = HogFunction.objects.filter(
        team_id=team_id,
        type="internal_destination",
        enabled=True,
        deleted=False,
        filters__events__contains=[{"id": event.value}],
    ).exists()
    cache.set(cache_key, has_subscriber, SUBSCRIBER_CACHE_SECONDS)
    return has_subscriber


def _build_properties(
    *,
    team_id: int,
    schema_id: str,
    event: SyncAlertEvent,
    kind: SyncAlertKind | None,
    job_id: str | None,
) -> dict[str, Any] | None:
    include_error = event == SyncAlertEvent.FAILED
    context = get_sync_alert_context(team_id, schema_id, job_id, include_error=include_error)
    if context is None:
        return None

    source_url = f"{settings.SITE_URL}/project/{team_id}/data-management/sources/managed-{context.source_id}/syncs"

    # Only a failed event carries the error. A billing-limited run keeps the error of the last real
    # failure on the schema, which is not the reason for a billing event. `latest_error` is the copy
    # the Syncs tab shows. The internal error can hold driver text and connection details.
    error = (context.latest_error or "Unknown error")[:MAX_ERROR_LENGTH] if include_error else None

    return {
        "source_id": str(context.source_id),
        "source_type": context.source_type,
        "source_prefix": (context.source_prefix or "").rstrip("_"),
        "schema_id": str(context.schema_id),
        "schema_name": context.schema_label or context.schema_name,
        "job_id": str(context.job_id) if context.job_id else None,
        "status": context.status,
        "kind": kind.value if kind else None,
        "error": error,
        "rows_synced": context.rows_synced,
        "paused": context.sync_halted,
        "failed_runs_in_a_row": context.failed_runs_in_a_row,
        "source_url": source_url,
        "schema_url": f"{source_url}?schema={quote(context.schema_name)}",
        "finished_at": context.finished_at.isoformat() if context.finished_at else None,
    }
