from uuid import UUID

import structlog
from celery import shared_task
from prometheus_client import Counter

from posthog.ducklake.models import DuckgresServerTeam
from posthog.redis import get_client, redis
from posthog.scoping_audit import skip_team_scope_audit

from products.data_warehouse.backend.logic.external_data_source.notifications import (
    get_team_ids_with_recent_sync_failures,
    notify_external_data_sync_failures,
)
from products.data_warehouse.backend.managed_warehouse_connection import reconcile_managed_warehouse_tables

logger = structlog.get_logger(__name__)

# Digest tasks scheduled, by trigger: "inline" (a sync just failed, from jobs.py),
# "cdc" (a CDC failure path), or "catchup" (the daily sweep below). increase(...{trigger="catchup"}[1d]) is the
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
# Live introspection of a large catalog plus the credential handshake can far exceed the
# digest bound; the select_for_update guards make an overlap harmless, but keep the lock
# long enough that it stays the normal exclusion mechanism.
MANAGED_WAREHOUSE_RECONCILE_LOCK_TIMEOUT_SECONDS = 600
MANAGED_WAREHOUSE_RECONCILE_INTERVAL_SECONDS = 60


@shared_task(ignore_result=True, name="products.data_warehouse.backend.tasks.reconcile_managed_warehouse_tables")
@skip_team_scope_audit
def reconcile_managed_warehouse_tables_task(team_id: int, organization_id: str) -> None:
    try:
        with get_client().lock(
            f"managed_warehouse_reconcile:{team_id}",
            timeout=MANAGED_WAREHOUSE_RECONCILE_LOCK_TIMEOUT_SECONDS,
            blocking=False,
        ):
            reconcile_managed_warehouse_tables(team_id=team_id, organization_id=organization_id)
    except redis.exceptions.LockError:
        logger.info("Managed warehouse table reconciliation already in flight", team_id=team_id)


def schedule_managed_warehouse_tables_reconcile(*, team_id: int, organization_id: str | UUID) -> None:
    client = get_client()
    schedule_key = f"managed_warehouse_reconcile_scheduled:{team_id}"
    if not client.set(schedule_key, "1", ex=MANAGED_WAREHOUSE_RECONCILE_INTERVAL_SECONDS, nx=True):
        return
    try:
        reconcile_managed_warehouse_tables_task.delay(team_id=team_id, organization_id=str(organization_id))
    except Exception:
        client.delete(schedule_key)
        raise


@shared_task(
    ignore_result=True,
    name="products.data_warehouse.backend.tasks.soft_delete_managed_warehouse_sources",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=3600,
    max_retries=10,
)
@skip_team_scope_audit
def soft_delete_managed_warehouse_sources_task(organization_id: str) -> None:
    from products.data_warehouse.backend.managed_warehouse_connection import (  # noqa: PLC0415
        soft_delete_managed_warehouse_sources,
    )

    soft_delete_managed_warehouse_sources(organization_id=organization_id)


def schedule_soft_delete_managed_warehouse_sources(*, organization_id: str | UUID) -> None:
    soft_delete_managed_warehouse_sources_task.delay(organization_id=str(organization_id))


@shared_task(ignore_result=True, name="products.data_warehouse.backend.tasks.reconcile_all_managed_warehouse_tables")
@skip_team_scope_audit
def reconcile_all_managed_warehouse_tables_task() -> None:
    memberships = (
        DuckgresServerTeam.objects.filter(backfill_enabled=True, table_suffix__isnull=False)
        .exclude(table_suffix="")
        .values_list("team_id", "server__organization_id")
        .iterator()
    )
    for team_id, organization_id in memberships:
        schedule_managed_warehouse_tables_reconcile(team_id=team_id, organization_id=organization_id)


def schedule_external_data_failure_digest(team_id: int, *, trigger: str = "inline") -> None:
    """Schedule the per-team failure digest email after the burst-collapse delay.

    Safe to call on every failure: the task dedupes via a per-team lock and a
    per-digest-day campaign key.
    """
    send_external_data_failure_digest_task.apply_async(
        args=[team_id], countdown=EXTERNAL_DATA_FAILURE_DIGEST_DELAY_SECONDS
    )
    EXTERNAL_DATA_FAILURE_DIGEST_SCHEDULED_COUNTER.labels(trigger=trigger).inc()


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


@shared_task(ignore_result=True, name="products.data_warehouse.backend.tasks.sync_team_earliest_event_date")
@skip_team_scope_audit  # DuckgresServerTeam is on the default Django manager
def sync_team_earliest_event_date(team_id: int) -> None:
    """Resolve, cache, and mirror a team's earliest event date after provision/onboard.

    Dual-write: the clamped earliest event date is stored on the Django
    ``DuckgresServerTeam`` row — the full-backfill sensor's read source — and mirrored to
    the team's duckgres control-plane row.
    Idempotent: an already-cached date is never recomputed, and both writes are upserts.
    Best-effort on the control-plane side: a failed push is logged and dropped — the
    sensor's reconciliation pass re-pushes it on a later tick.

    A team with no events yet is left unresolved (NULL), NOT cached as the no-history
    sentinel: this task runs seconds after provision/onboard, when a brand-new project
    plausibly hasn't ingested its first events. A cached date is final (nothing
    re-resolves a non-NULL value), so persisting the sentinel here would permanently
    exclude the team from historical backfill. The full-backfill sensor resolves it
    later, when "no events" is a meaningful answer.
    """
    # Deferred: ducklake.common pulls duckdb in, and posthog.models must not load while
    # Celery imports task modules — keep both off this module's import path.
    from posthog.ducklake.common import NO_HISTORY_SENTINEL, resolve_team_earliest_event_date  # noqa: PLC0415
    from posthog.ducklake.models import DuckgresServerTeam  # noqa: PLC0415

    from products.data_warehouse.backend.presentation.views.managed_warehouse import (  # noqa: PLC0415
        push_team_earliest_event_date,
    )

    bf = DuckgresServerTeam.objects.select_related("server").filter(team_id=team_id).first()
    if bf is None:
        logger.info("No duckling membership row for team; skipping earliest event date sync", team_id=team_id)
        return
    if bf.earliest_event_date is None:
        resolved = resolve_team_earliest_event_date(team_id)
        if resolved == NO_HISTORY_SENTINEL:
            logger.info("No events for team yet; leaving earliest event date unresolved", team_id=team_id)
            return
        bf.earliest_event_date = resolved
        bf.save(update_fields=["earliest_event_date"])
    push_team_earliest_event_date(bf.server.organization_id, team_id, bf.earliest_event_date)


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
