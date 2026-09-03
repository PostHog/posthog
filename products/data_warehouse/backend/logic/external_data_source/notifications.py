import datetime as dt
from urllib.parse import quote

from django.conf import settings
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

import structlog

from posthog.tasks.email import send_external_data_failure_digest

from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema
from products.warehouse_sources.backend.facade.types import ExternalDataJobStatus, ExternalDataSchemaStatus

logger = structlog.get_logger(__name__)

# A broken source can fail hundreds of schemas at once; cap the email table and
# point at the sources page for the rest. Omitted schemas are still stamped as
# notified — the email communicates them in aggregate via the "+N more" line.
MAX_SCHEMAS_PER_DIGEST_EMAIL = 30

# Re-notify a schema that stays failed this long after its last email. A paused
# schema never runs again, so it produces no newer failed job to re-trigger the
# digest — without this it gets exactly one email, then silence for weeks while
# its data goes stale. The catch-up sweep runs daily, so it picks the schema up
# the first day past this age and stamps a fresh time, spacing reminders evenly.
RENOTIFY_STILL_FAILING_AFTER = dt.timedelta(days=7)


def get_team_ids_with_recent_sync_failures(
    lookback: dt.timedelta = dt.timedelta(hours=26),
    renotify_after: dt.timedelta = RENOTIFY_STILL_FAILING_AFTER,
) -> list[int]:
    """Teams with still-failing schemas that need a digest.

    Powers the daily catch-up digest. It flushes two groups:

    - Failures that the one-email-per-day block swallowed. A failure counts only
      if it is newer than the schema's `last_error_notified_at` stamp, so failures
      already covered by an earlier digest do not trigger a duplicate.
    - Schemas that stay failed but produce no newer failed run — a paused schema
      never syncs again. Their last email is older than `renotify_after`, so they
      get a reminder instead of silence.

    The lookback exceeds the 24h digest day on purpose: a failure just after the
    10:00 UTC rollover, blocked because that digest day's email already went out,
    is 24h15m+ old by the next catch-up run — a 24h lookback would drop it forever
    for paused schemas. The stamp check above keeps the wider window duplicate-free.
    """
    now = dt.datetime.now(dt.UTC)
    cutoff = now - lookback
    renotify_cutoff = now - renotify_after
    # Drive from the schema side: the jobs table grows with every sync run and has
    # no index on (status, finished_at), so starting there would seq-scan it daily.
    # Schemas are one row each, and their jobs are reachable via the schema_id FK index.
    unnotified_failed_job = ExternalDataJob.objects.filter(
        schema_id=OuterRef("id"),
        status=ExternalDataJobStatus.FAILED,
        finished_at__gte=cutoff,
    ).filter(Q(schema__last_error_notified_at__isnull=True) | Q(finished_at__gt=OuterRef("last_error_notified_at")))
    return list(
        ExternalDataSchema.objects.exclude(deleted=True)
        .exclude(source__deleted=True)
        .filter(status=ExternalDataSchemaStatus.FAILED)
        .filter(Exists(unnotified_failed_job) | Q(last_error_notified_at__lt=renotify_cutoff))
        .values_list("team_id", flat=True)
        .distinct()
    )


def notify_external_data_sync_failures(
    team_id: int, renotify_after: dt.timedelta = RENOTIFY_STILL_FAILING_AFTER
) -> None:
    """Email the team a digest of failing external data schemas that need a notification.

    A schema is listed when it was never notified, has a failed run newer than its last
    notification, or has stayed failed for longer than `renotify_after` since its last
    email. The last case reminds the team about a paused schema, which never runs again
    and so produces no newer failed run to re-trigger the digest on its own. Schemas of a
    deleted source are excluded entirely. Runs inside the digest Celery task; exceptions
    are swallowed so a notification problem never crash-loops the task. Throttling to one
    email per team per digest day happens in the email layer via the MessagingRecord
    campaign key, so scheduling this for every failed job is safe.
    """
    try:
        renotify_cutoff = dt.datetime.now(dt.UTC) - renotify_after
        newer_failed_job = ExternalDataJob.objects.filter(
            schema_id=OuterRef("id"),
            status=ExternalDataJobStatus.FAILED,
            finished_at__gt=OuterRef("last_error_notified_at"),
        )
        failing_schemas = list(
            ExternalDataSchema.objects.exclude(deleted=True)
            .exclude(source__deleted=True)
            .filter(team_id=team_id, status=ExternalDataSchemaStatus.FAILED)
            .filter(
                Q(last_error_notified_at__isnull=True)
                | Q(last_error_notified_at__lt=renotify_cutoff)
                | Exists(newer_failed_job)
            )
            .select_related("source")
            .order_by("name")
        )
        if not failing_schemas:
            return

        # Halted schemas first — they need user action. sync_halted reads sync_type_config,
        # so this sort happens in Python, not SQL.
        failing_schemas.sort(key=lambda schema: not schema.sync_halted)

        # The template regroups on source_id, which needs schemas consecutive per
        # source; sources with halted schemas come first.
        schemas_by_source: dict[str, list[ExternalDataSchema]] = {}
        for schema in failing_schemas:
            schemas_by_source.setdefault(str(schema.source_id), []).append(schema)
        ordered_schemas = [
            schema
            for group in sorted(
                schemas_by_source.values(),
                key=lambda group: (not group[0].sync_halted, str(group[0].source.source_type).lower()),
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
                    "paused": schema.sync_halted,
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
