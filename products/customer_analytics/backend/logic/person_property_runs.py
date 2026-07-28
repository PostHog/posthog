"""Persists person-property sync/backfill run outcomes.

Registered as the data-import pipeline's run recorder (see apps.ready). Called from the warehouse
sync/backfill activities, outside request context, so it scopes explicitly with ``for_team``. Writes
a ``CustomPropertySyncRun`` row and folds the outcome back onto the source's status fields so the
account-path ``sourceSyncStatus`` UI helper works for person sources too.
"""

from datetime import datetime

import structlog

from posthog.exceptions_capture import capture_exception

from products.customer_analytics.backend.models import (
    CustomPropertySource,
    CustomPropertySyncRun,
    SyncStatus,
    SyncTrigger,
)
from products.warehouse_sources.backend.facade.hooks import PersonPropertySyncRunRecord

logger = structlog.get_logger(__name__)

# Auto-disable a source after this many consecutive failures, matching the account sync path.
MAX_CONSECUTIVE_SYNC_FAILURES = 5

# Triggers that pre-create a "running" row (from the UI/auto path) which this recorder then reconciles
# to its terminal state, so one backfill is one row rather than a running + a completed pair.
_UI_TRIGGERS = frozenset({SyncTrigger.MANUAL.value, SyncTrigger.BACKFILL.value})


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def record_sync_run(record: PersonPropertySyncRunRecord) -> None:
    """Create the run row and update the source's status fields. Swallows its own errors: run
    bookkeeping must never fail the sync that produced it."""
    log = logger.bind(
        team_id=record.team_id,
        source_id=record.source_id,
        schema_id=record.schema_id,
        trigger=record.trigger,
        status=record.status,
    )
    try:
        source = CustomPropertySource.objects.for_team(record.team_id).filter(id=record.source_id).first()
        if source is None:
            # The source was deleted between the run starting and finishing — nothing to record.
            log.info("person-property run recorder: source no longer exists, skipping")
            return

        finished_at = _parse_iso(record.finished_at)
        succeeded = record.status == SyncStatus.COMPLETED.value

        # Manual/backfill runs pre-create a "running" row (UI progress + double-submit guard);
        # reconcile the newest one to its terminal state so it's one row, not a running+terminal
        # pair. Scheduled runs ride a warehouse import job whose activity retries up to 3 times, so
        # dedup them on job_id: a retried attempt updates the one row instead of inserting a fresh
        # row (and re-counting the failure) each attempt.
        run = None
        if record.trigger in _UI_TRIGGERS:
            run = (
                CustomPropertySyncRun.objects.for_team(record.team_id)
                .filter(source=source, status=SyncStatus.RUNNING.value)
                .order_by("-created_at")
                .first()
            )
        elif record.job_id:
            run = (
                CustomPropertySyncRun.objects.for_team(record.team_id)
                .filter(source=source, job_id=record.job_id)
                .order_by("-created_at")
                .first()
            )
        # Captured before the row is overwritten below: an activity retry re-recording the same
        # already-failed job must not increment consecutive_failures again (that would auto-disable
        # the source from retry noise rather than distinct failed syncs).
        already_failed = run is not None and run.status == SyncStatus.FAILED.value

        fields = {
            "schema_id": record.schema_id or None,
            "job_id": record.job_id,
            "trigger": record.trigger,
            "status": record.status,
            "started_at": _parse_iso(record.started_at),
            "finished_at": finished_at,
            "rows_read": record.rows_read,
            "changed": record.changed,
            "existing": record.existing,
            "produced": record.produced,
            "skipped_missing_person": record.skipped_missing_person,
            "error": record.error,
        }
        if run is not None:
            for attr, value in fields.items():
                setattr(run, attr, value)
            run.save()
        else:
            CustomPropertySyncRun.objects.for_team(record.team_id).create(
                team_id=record.team_id, source=source, **fields
            )

        if succeeded:
            # Idempotent: safe to fold onto the source again if a prior attempt failed then a retry
            # succeeded — resets the failure streak and stamps the last-synced time.
            source.last_synced_at = finished_at
            source.last_sync_error = None
            source.consecutive_failures = 0
            source.save(update_fields=["last_synced_at", "last_sync_error", "consecutive_failures", "updated_at"])
            log.info(
                "person-property run recorded: completed",
                rows_read=record.rows_read,
                changed=record.changed,
                existing=record.existing,
                produced=record.produced,
                skipped_missing_person=record.skipped_missing_person,
            )
        else:
            if not already_failed:
                source.consecutive_failures = (source.consecutive_failures or 0) + 1
            source.last_sync_error = record.error
            auto_disabled = source.consecutive_failures >= MAX_CONSECUTIVE_SYNC_FAILURES
            if auto_disabled:
                source.is_enabled = False
            source.save(update_fields=["consecutive_failures", "last_sync_error", "is_enabled", "updated_at"])
            log.warning(
                "person-property run recorded: failed",
                consecutive_failures=source.consecutive_failures,
                auto_disabled=auto_disabled,
                error=record.error,
            )
            if auto_disabled:
                log.error(
                    "person-property source auto-disabled after consecutive failures",
                    consecutive_failures=source.consecutive_failures,
                )
    except Exception as e:
        # Run bookkeeping must never fail the sync/backfill that produced it, but the failure itself
        # is worth surfacing — a persistently failing recorder means the UI silently drifts from reality.
        log.exception("person-property run recorder failed")
        capture_exception(e)
