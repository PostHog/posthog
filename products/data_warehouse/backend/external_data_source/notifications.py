import datetime as dt
from urllib.parse import quote

from django.conf import settings

import structlog

from posthog.tasks.email import send_external_data_failure_digest

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)


def get_team_ids_with_recent_sync_failures(lookback: dt.timedelta = dt.timedelta(hours=24)) -> list[int]:
    """Teams with still-failing schemas whose latest failure happened within the lookback.

    Powers the daily catch-up digest: failures that the one-email-per-day block
    swallowed get flushed the next day — including schemas that were paused and
    will never produce another failed run to re-trigger the inline path.
    """
    cutoff = dt.datetime.now(dt.UTC) - lookback
    return list(
        ExternalDataJob.objects.filter(
            status=ExternalDataJob.Status.FAILED,
            finished_at__gte=cutoff,
            schema__status=ExternalDataSchema.Status.FAILED,
        )
        .exclude(schema__deleted=True)
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

        send_external_data_failure_digest(team_id, items)
    except Exception:
        logger.exception("Failed to send external data sync failure digest", team_id=team_id)
