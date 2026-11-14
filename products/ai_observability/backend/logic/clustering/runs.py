from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import NotFound, Throttled, ValidationError

from posthog.models.user import User

from ...facade.clustering_contracts import ClusteringRunContext, ClusteringRunRef, ClusteringRunUpdate
from ...models.clustering_config import ClusteringConfig
from ...models.clustering_job import ClusteringJob
from ...models.clustering_run import ACTIVE_CLUSTERING_RUN_STATUSES, ClusteringRun, ClusteringRunStatus
from .constants import MIN_CLUSTERING_ITEMS, clustering_lookback_days
from .permissions import can_access_clustering_filters, validate_clustering_filters

FIRST_RUNS_PER_HOUR = 10


def request_first_runs(team_id: int, user: User, retry_job_id: UUID | None = None) -> None:
    with transaction.atomic():
        config = ClusteringConfig.objects.select_for_update().filter(team_id=team_id, enabled=True).first()
        if config is None:
            if retry_job_id:
                raise ValidationError("Enable clustering before retrying a job.")
            return
        jobs = ClusteringJob.objects.filter(team_id=team_id, enabled=True).order_by("created_at")
        if retry_job_id:
            jobs = jobs.filter(id=retry_job_id)
            if not jobs.exists():
                raise NotFound("Clustering job not found.")
        for job in jobs:
            latest = ClusteringRun.objects.for_team(team_id).filter(job=job).order_by("-created_at").first()
            if latest and latest.status == ClusteringRunStatus.COMPLETED:
                continue
            if latest and latest.status in ACTIVE_CLUSTERING_RUN_STATUSES:
                continue
            if latest and latest.status == ClusteringRunStatus.FAILED and retry_job_id is None:
                continue
            validate_clustering_filters(team_id, user, job.event_filters)
            recent = ClusteringRun.objects.for_team(team_id).filter(created_at__gt=timezone.now() - timedelta(hours=1))
            if recent.count() >= FIRST_RUNS_PER_HOUR:
                oldest = recent.earliest("created_at")
                wait = (oldest.created_at + timedelta(hours=1) - timezone.now()).total_seconds()
                raise Throttled(
                    wait=max(1, wait), detail="This project has started 10 clustering runs in the last hour."
                )
            run = ClusteringRun(team_id=team_id, job=job, requested_by=user, event_filters=job.event_filters)
            run.workflow_id = f"ai-observability-clustering-first-run-{run.id}"
            run.save()


def get_run_context(ref: ClusteringRunRef) -> ClusteringRunContext | None:
    run = (
        ClusteringRun.objects.for_team(ref.team_id).select_related("job", "requested_by").filter(id=ref.run_id).first()
    )
    if run is None:
        return None
    if run.job is None or run.requested_by is None or not run.requested_by.is_active:
        update_run(ClusteringRunUpdate(ref=ref, status=ClusteringRunStatus.CANCELED))
        return None
    active = (
        run.status in ACTIVE_CLUSTERING_RUN_STATUSES
        and run.job.enabled
        and run.requested_by.organization_memberships.filter(organization__team__id=ref.team_id).exists()
        and can_access_clustering_filters(ref.team_id, run.requested_by, run.event_filters)
        and ClusteringConfig.objects.filter(
            team_id=ref.team_id, enabled=True, team__organization__is_ai_data_processing_approved=True
        ).exists()
    )
    if not active and run.status in ACTIVE_CLUSTERING_RUN_STATUSES:
        update_run(ClusteringRunUpdate(ref=ref, status=ClusteringRunStatus.CANCELED))
    return ClusteringRunContext(
        active=active,
        job_id=str(run.job_id),
        job_name=run.job.name,
        analysis_level=run.job.analysis_level,
        event_filters=run.event_filters,
        user_id=run.requested_by_id,
        minimum=MIN_CLUSTERING_ITEMS,
        lookback_days=clustering_lookback_days(run.job.analysis_level),
    )


def update_run(update: ClusteringRunUpdate) -> None:
    changes: dict = {"status": update.status, "updated_at": timezone.now(), "failure_reason": update.failure_reason}
    if update.result_run_id:
        changes["result_run_id"] = update.result_run_id
    for field in ("eligible_count", "prepared_count", "cluster_count"):
        value = getattr(update, field)
        if value is not None:
            changes[field] = value
    if update.status not in ACTIVE_CLUSTERING_RUN_STATUSES:
        changes["finished_at"] = timezone.now()
    runs = ClusteringRun.objects.for_team(update.ref.team_id).filter(
        id=update.ref.run_id, status__in=ACTIVE_CLUSTERING_RUN_STATUSES
    )
    if update.failure_reason == "could_not_start":
        runs = runs.filter(status=ClusteringRunStatus.QUEUED)
    runs.update(**changes)
