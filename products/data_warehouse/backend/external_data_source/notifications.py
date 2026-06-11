from urllib.parse import quote

from django.conf import settings

import structlog

from posthog.tasks.email import send_external_data_failure_digest

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)

ERROR_SNIPPET_MAX_LENGTH = 300


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
            error = schema.latest_error or "Unknown error"
            if len(error) > ERROR_SNIPPET_MAX_LENGTH:
                error = error[: ERROR_SNIPPET_MAX_LENGTH - 1] + "…"
            items.append(
                {
                    "schema_name": schema.name,
                    "source_type": schema.source.source_type,
                    "error": error,
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
