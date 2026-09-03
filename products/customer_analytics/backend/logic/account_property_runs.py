from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.customer_analytics.backend.models import CustomPropertySource, TargetType
from products.customer_analytics.backend.models.custom_property_sync_run import (
    CustomPropertySyncRun,
    SyncPhase,
    SyncSegment,
    SyncStatus,
    SyncTrigger,
)


@frozen
class AccountPropertySyncRunContext:
    team_id: int
    saved_query_id: str
    job_id: str


@frozen
class AccountPropertySyncRunOutcome:
    source_id: UUID
    rows_read: int
    changed: int
    matched: int
    written: int
    error: str | None = None


_ACCOUNT_SEGMENTS = {segment.value for segment in SyncSegment}
_MAX_CONSECUTIVE_SYNC_FAILURES = 5


def start_account_property_sync_runs(
    context: AccountPropertySyncRunContext,
    *,
    workflow_id: str | None,
    workflow_run_id: str | None,
) -> None:
    source_ids = list(
        CustomPropertySource.objects.for_team(context.team_id)
        .filter(
            saved_query_id=context.saved_query_id,
            is_enabled=True,
            definition__target_type=TargetType.ACCOUNT.value,
            source_column__isnull=False,
        )
        .values_list("id", flat=True)
    )
    if not source_ids:
        return

    with transaction.atomic():
        existing_runs = {
            (run.source_id, run.segment): run
            for run in CustomPropertySyncRun.objects.for_team(context.team_id)
            .select_for_update()
            .filter(source_id__in=source_ids, job_id=context.job_id)
            .order_by("created_at")
        }
        started_at = timezone.now()
        for source_id in source_ids:
            for segment in SyncSegment:
                run = existing_runs.get((source_id, segment.value))
                if run is None:
                    CustomPropertySyncRun.objects.for_team(context.team_id).create(
                        team_id=context.team_id,
                        source_id=source_id,
                        saved_query_id=context.saved_query_id,
                        job_id=context.job_id,
                        segment=segment.value,
                        phase=SyncPhase.STAGING.value,
                        attempt=0,
                        workflow_id=workflow_id,
                        workflow_run_id=workflow_run_id,
                        trigger=SyncTrigger.SCHEDULED.value,
                        status=SyncStatus.RUNNING.value,
                        started_at=started_at,
                    )
                    continue
                if run.status == SyncStatus.COMPLETED.value:
                    continue
                run.status = SyncStatus.RUNNING.value
                run.phase = SyncPhase.STAGING.value
                run.attempt = 0
                run.workflow_id = workflow_id
                run.workflow_run_id = workflow_run_id
                run.finished_at = None
                run.rows_read = 0
                run.changed = 0
                run.existing = 0
                run.produced = 0
                run.skipped_missing_person = 0
                run.error = None
                run.save(
                    update_fields=[
                        "status",
                        "phase",
                        "attempt",
                        "workflow_id",
                        "workflow_run_id",
                        "finished_at",
                        "rows_read",
                        "changed",
                        "existing",
                        "produced",
                        "skipped_missing_person",
                        "error",
                    ]
                )


def update_account_property_sync_runs_phase(
    context: AccountPropertySyncRunContext,
    *,
    phase: SyncPhase,
    workflow_id: str | None,
    workflow_run_id: str | None,
    attempt: int,
    segment: SyncSegment | None = None,
) -> None:
    runs = CustomPropertySyncRun.objects.for_team(context.team_id).filter(
        job_id=context.job_id,
        saved_query_id=context.saved_query_id,
        status=SyncStatus.RUNNING.value,
    )
    if segment is not None:
        runs = runs.filter(segment=segment.value)
    if phase == SyncPhase.DISPATCHING:
        runs = runs.filter(phase__in=[SyncPhase.STAGING.value, SyncPhase.DISPATCHING.value])
    runs.update(
        phase=phase.value,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        attempt=attempt,
    )


def _update_source_status_for_terminal_runs(
    team_id: int,
    job_id: str,
    transitioned_source_ids: set[UUID],
) -> None:
    if not transitioned_source_ids:
        return

    runs_by_source_id: dict[UUID, list[CustomPropertySyncRun]] = {}
    for run in (
        CustomPropertySyncRun.objects.for_team(team_id)
        .select_for_update()
        .filter(source_id__in=transitioned_source_ids, job_id=job_id)
    ):
        runs_by_source_id.setdefault(run.source_id, []).append(run)

    sources_by_id = {
        source.id: source
        for source in CustomPropertySource.objects.for_team(team_id)
        .select_for_update()
        .filter(id__in=transitioned_source_ids)
    }
    for source_id, runs in runs_by_source_id.items():
        if {run.segment for run in runs} != _ACCOUNT_SEGMENTS or any(
            run.status == SyncStatus.RUNNING.value for run in runs
        ):
            continue

        source = sources_by_id.get(source_id)
        if source is None:
            continue

        failed_runs = [run for run in runs if run.status == SyncStatus.FAILED.value]
        if failed_runs:
            source.consecutive_failures = (source.consecutive_failures or 0) + 1
            source.last_sync_error = next((run.error for run in failed_runs if run.error), None)
            if source.consecutive_failures >= _MAX_CONSECUTIVE_SYNC_FAILURES:
                source.is_enabled = False
            source.save(
                update_fields=[
                    "consecutive_failures",
                    "last_sync_error",
                    "is_enabled",
                    "updated_at",
                ]
            )
            continue

        finished_at = max((run.finished_at for run in runs if run.finished_at is not None), default=None)
        if finished_at is None:
            continue
        source.last_synced_at = finished_at
        source.last_sync_error = None
        source.consecutive_failures = 0
        source.save(update_fields=["last_synced_at", "last_sync_error", "consecutive_failures", "updated_at"])


def finalize_account_property_sync_runs(
    context: AccountPropertySyncRunContext,
    *,
    status: SyncStatus,
    phase: SyncPhase,
    error: str | None = None,
    segment: SyncSegment | None = None,
) -> None:
    with transaction.atomic():
        runs = (
            CustomPropertySyncRun.objects.for_team(context.team_id)
            .select_for_update()
            .filter(
                job_id=context.job_id,
                saved_query_id=context.saved_query_id,
                status=SyncStatus.RUNNING.value,
            )
        )
        if segment is not None:
            runs = runs.filter(segment=segment.value)
        transitioned_source_ids = set(runs.values_list("source_id", flat=True))
        runs.update(
            status=status.value,
            phase=phase.value,
            finished_at=timezone.now(),
            error=error,
        )
        _update_source_status_for_terminal_runs(context.team_id, context.job_id, transitioned_source_ids)


def finish_account_property_sync_runs(
    context: AccountPropertySyncRunContext,
    segment: SyncSegment,
    outcomes: list[AccountPropertySyncRunOutcome],
    *,
    finished_at: datetime | None = None,
) -> None:
    if not outcomes:
        return

    outcomes_by_source_id = {outcome.source_id: outcome for outcome in outcomes}
    with transaction.atomic():
        runs = list(
            CustomPropertySyncRun.objects.for_team(context.team_id)
            .select_for_update()
            .filter(
                source_id__in=outcomes_by_source_id,
                job_id=context.job_id,
                segment=segment.value,
            )
        )
        completed_at = finished_at or timezone.now()
        transitioned_source_ids: set[UUID] = set()
        for run in runs:
            if run.status in {SyncStatus.COMPLETED.value, SyncStatus.FAILED.value}:
                continue
            outcome = outcomes_by_source_id[run.source_id]
            failed = outcome.error is not None
            run.status = SyncStatus.FAILED.value if failed else SyncStatus.COMPLETED.value
            run.phase = SyncPhase.SYNCING.value if failed else SyncPhase.COMPLETED.value
            run.finished_at = completed_at
            run.rows_read = outcome.rows_read
            run.changed = outcome.changed
            run.existing = outcome.matched
            run.produced = outcome.written
            run.skipped_missing_person = max(outcome.changed - outcome.matched, 0)
            run.error = outcome.error
            transitioned_source_ids.add(run.source_id)
            run.save(
                update_fields=[
                    "status",
                    "phase",
                    "finished_at",
                    "rows_read",
                    "changed",
                    "existing",
                    "produced",
                    "skipped_missing_person",
                    "error",
                ]
            )
        _update_source_status_for_terminal_runs(context.team_id, context.job_id, transitioned_source_ids)
