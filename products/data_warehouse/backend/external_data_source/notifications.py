import datetime as dt
from urllib.parse import quote

from django.conf import settings
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

import structlog

from posthog.tasks.email import send_external_data_failure_digest

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)


def get_team_ids_with_recent_sync_failures(lookback: dt.timedelta = dt.timedelta(hours=24)) -> list[int]:
    """Teams with still-failing schemas that have an un-communicated recent failure.

    Powers the daily catch-up digest: failures that the one-email-per-day block
    swallowed get flushed the next day — including schemas that were paused and
    will never produce another failed run to re-trigger the inline path. A failure
    counts only if it is newer than the schema's `last_error_notified_at` stamp,
    so failures already covered by an earlier digest don't trigger a duplicate.
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
        .filter(status=ExternalDataSchema.Status.FAILED)
        .filter(Exists(unnotified_failed_job))
        .values_list("team_id", flat=True)
        .distinct()
    )


def notify_external_data_sync_failures(team_id: int) -> None:
    """Email the team a digest of every currently-failing external data schema.

    Called inline from the job-status update path, so it must never raise — a
    notification problem can't be allowed to fail the status transition.
    Throttling to one email per team per day happens in the email layer via the
    MessagingRecord campaign key, so calling this on every failed job is safe.
    """
    try:
        failing_schemas = list(
            ExternalDataSchema.objects.exclude(deleted=True)
            .filter(team_id=team_id, status=ExternalDataSchema.Status.FAILED)
            .select_related("source")
            # Paused (should_sync=False) schemas first — they need user action.
            .order_by("should_sync", "name")
        )
        if not failing_schemas:
            return

        items = []
        for schema in failing_schemas:
            items.append(
                {
                    "schema_name": schema.name,
                    "source_type": schema.source.source_type,
                    # The template truncates for display (truncatechars), and the rendered
                    # HTML is what crosses the Celery boundary — no need to cap here.
                    "error": schema.latest_error or "Unknown error",
                    "paused": not schema.should_sync,
                    "url": (
                        f"{settings.SITE_URL}/project/{team_id}/data-management/sources/"
                        f"managed-{schema.source_id}/syncs?schema={quote(schema.name)}"
                    ),
                }
            )

        sent = send_external_data_failure_digest(team_id, items)
        if sent:
            # Mark every listed schema as communicated, so the daily catch-up only
            # re-triggers for failures that happened after this email went out.
            ExternalDataSchema.objects.filter(id__in=[schema.id for schema in failing_schemas]).update(
                last_error_notified_at=timezone.now()
            )
    except Exception:
        logger.exception("Failed to send external data sync failure digest", team_id=team_id)
