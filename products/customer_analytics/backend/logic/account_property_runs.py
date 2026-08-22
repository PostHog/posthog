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


def start_account_property_sync_runs(context: AccountPropertySyncRunContext, workflow_id: str | None) -> None:
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
    runs.update(phase=phase.value, workflow_id=workflow_id, attempt=attempt)


def finalize_account_property_sync_runs(
    context: AccountPropertySyncRunContext,
    *,
    status: SyncStatus,
    phase: SyncPhase,
    error: str | None = None,
    segment: SyncSegment | None = None,
) -> None:
    runs = CustomPropertySyncRun.objects.for_team(context.team_id).filter(
        job_id=context.job_id,
        saved_query_id=context.saved_query_id,
        status=SyncStatus.RUNNING.value,
    )
    if segment is not None:
        runs = runs.filter(segment=segment.value)
    runs.update(
        status=status.value,
        phase=phase.value,
        finished_at=timezone.now(),
        error=error,
    )


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
        for run in runs:
            if run.status == SyncStatus.COMPLETED.value:
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
