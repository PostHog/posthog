from functools import partial
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from rest_framework.exceptions import NotFound, ValidationError

from ...facade.clustering_contracts import ClusteringRunContext, ClusteringRunRef, ClusteringRunUpdate
from ...models.clustering_config import ClusteringConfig
from ...models.clustering_job import ClusteringJob
from ...models.clustering_run import ACTIVE_CLUSTERING_RUN_STATUSES, ClusteringRun, ClusteringRunStatus
from .constants import MIN_CLUSTERING_ITEMS, clustering_lookback_days


def request_first_runs(team_id: int, retry_job_id: UUID | None = None) -> None:
    from ...temporal.clustering_client import dispatch_clustering_run

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
                if latest.status == ClusteringRunStatus.QUEUED:
                    transaction.on_commit(partial(dispatch_clustering_run, team_id, str(latest.id)))
                continue
            if latest and latest.status == ClusteringRunStatus.FAILED and retry_job_id is None:
                continue
            run = ClusteringRun(team_id=team_id, job=job)
            run.workflow_id = f"ai-observability-clustering-first-run-{run.id}"
            run.save()
            transaction.on_commit(partial(dispatch_clustering_run, team_id, str(run.id)))


def get_run_context(ref: ClusteringRunRef) -> ClusteringRunContext | None:
    run = ClusteringRun.objects.for_team(ref.team_id).select_related("job").filter(id=ref.run_id).first()
    if run is None:
        return None
    active = (
        run.status in ACTIVE_CLUSTERING_RUN_STATUSES
        and run.job.enabled
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
        event_filters=run.job.event_filters,
        minimum=MIN_CLUSTERING_ITEMS,
        lookback_days=clustering_lookback_days(run.job.analysis_level),
    )


def update_run(update: ClusteringRunUpdate) -> None:
    changes: dict = {"status": update.status, "updated_at": timezone.now(), "failure_reason": update.failure_reason}
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
