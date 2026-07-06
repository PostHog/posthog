import datetime as dt
from urllib.parse import quote

from django.conf import settings
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

import structlog

from posthog.tasks.email import send_external_data_failure_digest

from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema

logger = structlog.get_logger(__name__)

# A broken source can fail hundreds of schemas at once; cap the email table and
# point at the sources page for the rest. Omitted schemas are still stamped as
# notified — the email communicates them in aggregate via the "+N more" line.
MAX_SCHEMAS_PER_DIGEST_EMAIL = 30


def get_team_ids_with_recent_sync_failures(lookback: dt.timedelta = dt.timedelta(hours=26)) -> list[int]:
    """Teams with still-failing schemas that have an un-communicated recent failure.

    Powers the daily catch-up digest: failures that the one-email-per-day block
    swallowed get flushed the next day — including schemas that were paused and
    will never produce another failed run to re-trigger the inline path. A failure
    counts only if it is newer than the schema's `last_error_notified_at` stamp,
    so failures already covered by an earlier digest don't trigger a duplicate.

    The lookback exceeds the 24h digest day on purpose: a failure just after the
    10:00 UTC rollover, blocked because that digest day's email already went out,
    is 24h15m+ old by the next catch-up run — a 24h lookback would drop it forever
    for paused schemas. The stamp check above keeps the wider window duplicate-free.
    """
    cutoff = dt.datetime.now(dt.UTC) - lookback
    # Drive from the schema side: the jobs table grows with every sync run and has
    # no index on (status, finished_at), so starting there would seq-scan it daily.
    # Schemas are one row each, and their jobs are reachable via the schema_id FK index.
    unnotified_failed_job = ExternalDataJob.objects.filter(
        schema_id=OuterRef("id"),
        status=ExternalDataJob.Status.FAILED,
        finished_at__gte=cutoff,
    ).filter(Q(schema__last_error_notified_at__isnull=True) | Q(finished_at__gt=OuterRef("last_error_notified_at")))
    return list(
        ExternalDataSchema.objects.exclude(deleted=True)
        .exclude(source__deleted=True)
        .filter(status=ExternalDataSchema.Status.FAILED)
        .filter(Exists(unnotified_failed_job))
        .values_list("team_id", flat=True)
        .distinct()
    )


def notify_external_data_sync_failures(team_id: int) -> None:
    """Email the team a digest of failing external data schemas with an un-communicated failure.

    A failure is reported once: a schema is listed only if it was never notified or
    has a failed run newer than its last notification. A stuck-but-stopped sync
    (deleted source, paused schema) has no newer run, so it drops out after the first
    digest instead of riding every later one. Schemas of a deleted source are excluded
    entirely. Runs inside the digest Celery task; exceptions are swallowed so a
    notification problem never crash-loops the task. Throttling to one email per team
    per digest day happens in the email layer via the MessagingRecord campaign key, so
    scheduling this for every failed job is safe.
    """
    try:
        newer_failed_job = ExternalDataJob.objects.filter(
            schema_id=OuterRef("id"),
            status=ExternalDataJob.Status.FAILED,
            finished_at__gt=OuterRef("last_error_notified_at"),
        )
        failing_schemas = list(
            ExternalDataSchema.objects.exclude(deleted=True)
            .exclude(source__deleted=True)
            .filter(team_id=team_id, status=ExternalDataSchema.Status.FAILED)
            .filter(Q(last_error_notified_at__isnull=True) | Exists(newer_failed_job))
            .select_related("source")
            # Paused (should_sync=False) schemas first — they need user action.
            .order_by("should_sync", "name")
        )
        if not failing_schemas:
            return

        # The template regroups on source_id, which needs schemas consecutive per
        # source; sources with paused schemas come first.
        schemas_by_source: dict[str, list[ExternalDataSchema]] = {}
        for schema in failing_schemas:
            schemas_by_source.setdefault(str(schema.source_id), []).append(schema)
        ordered_schemas = [
            schema
            for group in sorted(
                schemas_by_source.values(),
                key=lambda group: (group[0].should_sync, str(group[0].source.source_type).lower()),
            )
            for schema in group
        ]

        items = []
        for schema in ordered_schemas[:MAX_SCHEMAS_PER_DIGEST_EMAIL]:
            source_url = (
                f"{settings.SITE_URL}/project/{team_id}/data-management/sources/managed-{schema.source_id}/syncs"
            )
            items.append(
                {
                    # Prefer the human-readable label (e.g. a Slack channel name) over the
                    # raw identifier in `name` (e.g. a Slack channel id); fall back to name.
                    "schema_name": schema.label or schema.name,
                    "source_id": str(schema.source_id),
                    "source_type": schema.source.source_type,
                    "source_prefix": (schema.source.prefix or "").rstrip("_"),
                    "source_url": source_url,
                    # The template truncates for display (truncatechars), and the rendered
                    # HTML is what crosses the Celery boundary — no need to cap here.
                    "error": schema.latest_error or "Unknown error",
                    "paused": not schema.should_sync,
                    "url": f"{source_url}?schema={quote(schema.name)}",
                }
            )

        omitted_count = max(0, len(failing_schemas) - MAX_SCHEMAS_PER_DIGEST_EMAIL)
        sent = send_external_data_failure_digest(team_id, items, omitted_count=omitted_count)
        if sent:
            # Mark every listed schema as communicated, so the daily catch-up only
            # re-triggers for failures that happened after this email went out.
            ExternalDataSchema.objects.filter(team_id=team_id, id__in=[schema.id for schema in failing_schemas]).update(
                last_error_notified_at=timezone.now()
            )
    except Exception:
        logger.exception("Failed to send external data sync failure digest", team_id=team_id)
