import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from products.data_warehouse.backend.external_data_source.notifications import (
    get_team_ids_with_recent_sync_failures,
    notify_external_data_sync_failures,
)

logger = structlog.get_logger(__name__)

# Schemas of one source tend to fail within seconds of each other (e.g. a dead
# credential failing every schema on the next run). The digest waits this long so
# the whole burst lands in one email instead of racing the first failure's send.
EXTERNAL_DATA_FAILURE_DIGEST_DELAY_SECONDS = 15 * 60


@shared_task(ignore_result=True)
@skip_team_scope_audit
def send_external_data_failure_digest_task(team_id: int) -> None:
    notify_external_data_sync_failures(team_id)


@shared_task(ignore_result=True)
@skip_team_scope_audit
def send_external_data_failure_digest_catchup() -> None:
    """Flush sync failures the one-email-per-day block swallowed.

    Runs daily just after the date-keyed campaign block resets. Any team whose
    schemas failed in the last 24 hours and are still failing gets a fresh
    digest — this guarantees every error is eventually communicated, including
    schemas paused by a non-retryable error that will never fail again to
    re-trigger the inline notification path.
    """
    team_ids = get_team_ids_with_recent_sync_failures()
    for team_id in team_ids:
        send_external_data_failure_digest_task.delay(team_id)

    if team_ids:
        logger.info("Dispatched external data failure digest catch-up for %d teams", len(team_ids))
