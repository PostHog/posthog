"""Persists person-property sync/backfill run outcomes.

Registered as the warehouse pipeline's run recorder (see apps.ready). Called from the warehouse
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
from products.warehouse_sources.backend.facade.hooks import BINDING_KIND_SAVED_QUERY, PersonPropertySyncRunRecord

logger = structlog.get_logger(__name__)

# Auto-disable a source after this many consecutive failures, matching the account sync path.
MAX_CONSECUTIVE_SYNC_FAILURES = 5

# A run row is reconciled only within its own pipeline: the backfill path reads the whole table from
# S3, the sync path rides a warehouse import job. Keeping them apart means a scheduled sync can't
# resolve a backfill's in-progress row (and vice versa) when both are in flight for the same source.
_BACKFILL_TRIGGERS = frozenset({SyncTrigger.MANUAL.value, SyncTrigger.BACKFILL.value})
_SYNC_TRIGGERS = frozenset({SyncTrigger.SCHEDULED.value, SyncTrigger.SYNC.value})

# Triggers set by a user action. The pipeline reports every import-driven run as "scheduled", so a
# row created by "Sync now" keeps its own trigger when the terminal record lands on it.
_USER_TRIGGERS = frozenset({SyncTrigger.SYNC.value, SyncTrigger.MANUAL.value})


def _binding_fields(record: PersonPropertySyncRunRecord) -> dict[str, str | None]:
    """The run row's binding columns. Both are kept nullable and only one is ever set, so a run stays
    readable after the schema or view it read is deleted."""
    if record.binding_kind == BINDING_KIND_SAVED_QUERY:
        return {"schema_id": None, "saved_query_id": record.binding_id or None}
    return {"schema_id": record.binding_id or None, "saved_query_id": None}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _find_reconcilable_run(team_id: int, source, record: PersonPropertySyncRunRecord):
    """The existing row this record belongs to, or None to insert a new one.

    Scheduled runs ride a warehouse import job whose activity retries up to 3 times, so they dedup on
    job_id: a retried attempt updates the one row instead of inserting a fresh row (and re-counting
    the failure) each attempt. Otherwise the record reconciles the newest in-progress row from its own
    pipeline — either a placeholder the UI created on "Sync now"/"Backfill" (progress + double-submit
    guard) or the row the activity opened when it started."""
    runs = CustomPropertySyncRun.objects.for_team(team_id).filter(source=source)
    if record.job_id:
        run = runs.filter(job_id=record.job_id).order_by("-created_at").first()
        if run is not None:
            return run
    triggers = _BACKFILL_TRIGGERS if record.trigger in _BACKFILL_TRIGGERS else _SYNC_TRIGGERS
    return runs.filter(status=SyncStatus.RUNNING.value, trigger__in=triggers).order_by("-created_at").first()


def record_sync_run(record: PersonPropertySyncRunRecord) -> None:
    """Create or reconcile the run row and update the source's status fields. A ``running`` record
    only opens the row — the source's status fields are folded in when the run reaches a terminal
    state. Swallows its own errors: run bookkeeping must never fail the sync that produced it."""
    log = logger.bind(
        team_id=record.team_id,
        source_id=record.source_id,
        binding_kind=record.binding_kind,
        binding_id=record.binding_id,
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

        run = _find_reconcilable_run(record.team_id, source, record)
        # Captured before the row is overwritten below: an activity retry re-recording the same
        # already-failed job must not increment consecutive_failures again (that would auto-disable
        # the source from retry noise rather than distinct failed syncs).
        already_failed = run is not None and run.status == SyncStatus.FAILED.value

        fields: dict = {
            **_binding_fields(record),
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
            # The pipeline reports every import-driven run as "scheduled"; don't relabel a row the
            # user started that way.
            if run.trigger in _USER_TRIGGERS:
                fields.pop("trigger")
            for attr, value in fields.items():
                setattr(run, attr, value)
            run.save()
        else:
            CustomPropertySyncRun.objects.for_team(record.team_id).create(
                team_id=record.team_id, source=source, **fields
            )

        if record.status == SyncStatus.RUNNING.value:
            # The run has only opened — nothing to fold onto the source until it settles, and
            # clearing the last error here would hide a still-relevant failure.
            log.info("person-property run recorded: running")
            return

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
