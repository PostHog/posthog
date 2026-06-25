import structlog
from celery import shared_task
from prometheus_client import Counter

from posthog.redis import get_client, redis
from posthog.scoping_audit import skip_team_scope_audit

from products.data_warehouse.backend.logic.external_data_source.notifications import (
    get_team_ids_with_recent_sync_failures,
    notify_external_data_sync_failures,
)

logger = structlog.get_logger(__name__)

# Digest tasks scheduled, by trigger: "inline" (a sync just failed, from jobs.py)
# vs "catchup" (the daily sweep below). increase(...{trigger="catchup"}[1d]) is the
# catch-up fan-out — how many teams the daily sweep re-notifies. The inline count is
# the burst denominator: comparing it to delivered emails shows how hard the 15-min
# countdown + campaign-key dedup are collapsing bursts.
EXTERNAL_DATA_FAILURE_DIGEST_SCHEDULED_COUNTER = Counter(
    "external_data_failure_digest_scheduled_total",
    "External data failure digest tasks scheduled, by trigger source.",
    labelnames=["trigger"],
)

# Task executions, by outcome: "processed" took the per-team lock and ran the send
# funnel; "lock_contended" lost the race to a concurrent send and skipped. A high
# lock_contended share is the per-team serialization working, not a problem.
EXTERNAL_DATA_FAILURE_DIGEST_TASK_COUNTER = Counter(
    "external_data_failure_digest_task_total",
    "External data failure digest task executions, by outcome.",
    labelnames=["outcome"],
)

# Schemas of one source tend to fail within seconds of each other (e.g. a dead
# credential failing every schema on the next run). The digest waits this long so
# the whole burst lands in one email instead of racing the first failure's send.
EXTERNAL_DATA_FAILURE_DIGEST_DELAY_SECONDS = 15 * 60

# Generous bound on one digest build + synchronous send; the lock auto-expires
# after this if a worker dies mid-flight.
EXTERNAL_DATA_FAILURE_DIGEST_LOCK_TIMEOUT_SECONDS = 120


@shared_task(ignore_result=True, name="products.data_warehouse.backend.tasks.send_external_data_failure_digest_task")
@skip_team_scope_audit
def send_external_data_failure_digest_task(team_id: int) -> None:
    # Serialize per team: a racing task could mistake an in-flight winner's delivery
    # for its own and stamp schemas the delivered email never contained, permanently
    # silencing a paused schema. The loser skips instead — anything the winner didn't
    # cover stays un-stamped for a later task or the catch-up.
    try:
        with get_client().lock(
            f"external_data_failure_digest:{team_id}",
            timeout=EXTERNAL_DATA_FAILURE_DIGEST_LOCK_TIMEOUT_SECONDS,
            blocking=False,
        ):
            notify_external_data_sync_failures(team_id)
            EXTERNAL_DATA_FAILURE_DIGEST_TASK_COUNTER.labels(outcome="processed").inc()
    except redis.exceptions.LockError:
        EXTERNAL_DATA_FAILURE_DIGEST_TASK_COUNTER.labels(outcome="lock_contended").inc()
        logger.info("External data failure digest already in flight for team, skipping", team_id=team_id)


@shared_task(ignore_result=True, name="products.data_warehouse.backend.tasks.send_external_data_failure_digest_catchup")
@skip_team_scope_audit
def send_external_data_failure_digest_catchup() -> None:
    """Flush sync failures the one-email-per-day block swallowed.

    Runs daily just after the digest day rolls over (10:15 UTC, see
    EXTERNAL_DATA_DIGEST_DAY_BOUNDARY_HOUR_UTC) and the date-keyed campaign
    block resets. Any team whose schemas failed in the last 24 hours and are
    still failing gets a fresh digest — this guarantees every error is
    eventually communicated, including schemas paused by a non-retryable error
    that will never fail again to re-trigger the inline notification path.
    """
    team_ids = get_team_ids_with_recent_sync_failures()
    for team_id in team_ids:
        send_external_data_failure_digest_task.delay(team_id)

    if team_ids:
        EXTERNAL_DATA_FAILURE_DIGEST_SCHEDULED_COUNTER.labels(trigger="catchup").inc(len(team_ids))
        logger.info("Dispatched external data failure digest catch-up for %d teams", len(team_ids))
