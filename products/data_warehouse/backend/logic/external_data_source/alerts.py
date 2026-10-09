from enum import StrEnum
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.cdp.validation import InputsItemSerializer, compile_hog
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.models.messaging import MessagingRecord
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers
from posthog.tasks.email import (
    ExternalDataFailureDigestItem,
    external_data_failure_digest_campaign_key,
    external_data_failure_digest_day,
    get_members_to_notify_for_pipeline_error,
)

from products.cdp.backend.facade.models import HogFunction
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.warehouse_sources.backend.facade.api import get_sync_alert_context
from products.warehouse_sources.backend.facade.types import ExternalDataJobStatus, ExternalDataSchemaStatus

logger = structlog.get_logger(__name__)

SYNC_ALERT_EVENTS = Counter(
    "dwh_sync_alert_events_total",
    "Sync alert internal events, by event name and outcome",
    labelnames=["event", "outcome"],
)

MAX_ERROR_LENGTH = 1000
FAILURE_DIGEST_EVENT = "$data_warehouse_sync_failure_digest"
FAILURE_EMAIL_TEMPLATE_ID = "template-posthog-email"
MAX_DIGEST_SUMMARY_LENGTH = 3500

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


def failure_email_destination_enabled(team: Team) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            key="dwh-failure-email-destination",
            distinct_id=str(team.uuid),
            groups={"organization": str(team.organization_id), "project": str(team.id)},
            group_properties={
                "organization": {"id": str(team.organization_id)},
                "project": {"id": str(team.id)},
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def _has_failure_email_alert(team: Team) -> bool:
    return HogFunction.objects.filter(
        team_id=team.pk,
        template_id=FAILURE_EMAIL_TEMPLATE_ID,
        filters__events__contains=[{"id": FAILURE_DIGEST_EVENT}],
    ).exists()


def ensure_default_failure_email_alert(team: Team) -> None:
    if _has_failure_email_alert(team):
        return

    template = HogFunctionTemplate.get_template(FAILURE_EMAIL_TEMPLATE_ID)
    if template is None:
        logger.warning("Warehouse failure email template is missing", team_id=team.pk)
        SYNC_ALERT_EVENTS.labels(event=FAILURE_DIGEST_EVENT, outcome="template_missing").inc()
        return

    values = {
        "subject": "{event.properties.schema_count} table sync(s) need attention",
        "body": "These tables failed to sync:\n\n{event.properties.summary}",
        "action_url": "{event.properties.sources_url}",
        "action_label": "View sources",
    }
    inputs = {}
    for schema in template.inputs_schema:
        serializer = InputsItemSerializer(
            data={"value": values[schema["key"]]},
            context={"schema": schema, "function_type": "internal_destination"},
        )
        serializer.is_valid(raise_exception=True)
        inputs[schema["key"]] = serializer.validated_data

    # The digest task holds the per-team Redis lock to prevent concurrent inserts.
    with transaction.atomic():
        if _has_failure_email_alert(team):
            return
        hog_function = HogFunction.objects.create(
            team=team,
            created_by=None,
            template_id=template.template_id,
            hog_function_template=template,
            type="internal_destination",
            name="Email project members when table syncs fail",
            description="Send project members a daily email about tables that failed to sync.",
            enabled=True,
            hog=template.code,
            bytecode=template.bytecode or compile_hog(template.code, "internal_destination"),
            inputs_schema=template.inputs_schema,
            inputs=inputs,
            filters={"source": "internal-events", "events": [{"id": FAILURE_DIGEST_EVENT, "type": "events"}]},
        )
        transaction.on_commit(
            lambda: reload_hog_functions_on_workers(team_id=team.pk, hog_function_ids=[str(hog_function.id)]),
            robust=True,
        )


def build_failure_digest_summary(schemas: list[ExternalDataFailureDigestItem], omitted_count: int) -> str:
    lines = [
        f"{' '.join(item['source_type'].splitlines())} / {' '.join(item['schema_name'].splitlines())}: "
        f"{' '.join(item['error'][:200].splitlines())}{' (paused)' if item['paused'] else ''}"
        for item in schemas
    ]
    while True:
        summary = "\n".join([*lines, f"and {omitted_count} more"] if omitted_count else lines)
        if len(summary) <= MAX_DIGEST_SUMMARY_LENGTH:
            return summary
        lines.pop()
        omitted_count += 1


def emit_failure_digest(team: Team, schemas: list[ExternalDataFailureDigestItem], omitted_count: int) -> bool | None:
    digest_day = external_data_failure_digest_day()
    campaign_key = external_data_failure_digest_campaign_key(team.pk, digest_day)
    if MessagingRecord.objects.filter(campaign_key=campaign_key, sent_at__isnull=False).exists():
        SYNC_ALERT_EVENTS.labels(event=FAILURE_DIGEST_EVENT, outcome="deduped").inc()
        return False

    recipient_ids = [member.user_id for member in get_members_to_notify_for_pipeline_error(team, failure_rate=1.0)]
    if not recipient_ids:
        SYNC_ALERT_EVENTS.labels(event=FAILURE_DIGEST_EVENT, outcome="no_recipients").inc()
        return False

    ensure_default_failure_email_alert(team)
    if not _has_failure_email_alert(team):
        return None

    try:
        produce_internal_event(
            team_id=team.pk,
            event=InternalEventEvent(
                event=FAILURE_DIGEST_EVENT,
                distinct_id=f"team_{team.pk}",
                properties={
                    "$notify_user_ids": recipient_ids,
                    "schemas": schemas,
                    "schema_count": len(schemas) + omitted_count,
                    "omitted_count": omitted_count,
                    "digest_day": digest_day.isoformat(),
                    "sources_url": f"{settings.SITE_URL}/project/{team.pk}/data-management/sources",
                    "summary": build_failure_digest_summary(schemas, omitted_count),
                },
            ),
        )
        MessagingRecord.objects.update_or_create(
            campaign_key=campaign_key,
            email_hash=f"team_{team.pk}",
            defaults={"sent_at": timezone.now()},
        )
        SYNC_ALERT_EVENTS.labels(event=FAILURE_DIGEST_EVENT, outcome="produced").inc()
        return True
    except Exception:
        SYNC_ALERT_EVENTS.labels(event=FAILURE_DIGEST_EVENT, outcome="error").inc()
        raise


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
