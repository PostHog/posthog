import json
import hashlib
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from ...facade.clustering_contracts import ClusteringExecutionClaim, ClusteringExecutionRequest, ClusteringRunRef
from ...models.clustering_config import ClusteringConfig
from ...models.clustering_job import ClusteringJob
from ...models.clustering_run import ACTIVE_CLUSTERING_RUN_STATUSES, ClusteringRun, ClusteringRunStatus
from .eligibility import eligible_clustering_team_ids


def scope_key(analysis_level: str, event_filters: list[dict]) -> str:
    return hashlib.sha256(json.dumps([analysis_level, event_filters], sort_keys=True).encode()).hexdigest()[:32]


def acquire_execution(request: ClusteringExecutionRequest) -> ClusteringExecutionClaim | None:
    if request.team_id not in eligible_clustering_team_ids([request.team_id]):
        return None
    with transaction.atomic():
        config = ClusteringConfig.objects.select_for_update().get(team_id=request.team_id)
        if not config.enabled:
            return None
        job = ClusteringJob.objects.filter(id=request.job_id, team_id=request.team_id, enabled=True).first()
        if job is None or job.analysis_level != request.analysis_level or job.event_filters != request.event_filters:
            return None
        active = (
            ClusteringRun.objects.for_team(request.team_id)
            .filter(job=job, status__in=ACTIVE_CLUSTERING_RUN_STATUSES)
            .first()
        )
        if active:
            if str(active.id) == request.run_id or active.workflow_id == request.workflow_id:
                return ClusteringExecutionClaim(run_id=str(active.id), owned=not request.run_id)
            return None
        if request.run_id:
            return None
        run = ClusteringRun.objects.for_team(request.team_id).create(
            team_id=request.team_id,
            job=job,
            event_filters=job.event_filters,
            analysis_level=job.analysis_level,
            is_first_run=False,
            workflow_id=request.workflow_id,
            status=ClusteringRunStatus.PREPARING,
        )
        return ClusteringExecutionClaim(run_id=str(run.id), owned=True)


def execution_scope(ref: ClusteringRunRef) -> str | None:
    from .runs import get_run_context

    context = get_run_context(ref)
    if context is None or not context.active:
        return None
    return scope_key(context.analysis_level, context.event_filters)


def cancel_runs(team_id: int, job_id: UUID | None = None) -> None:
    from ...tasks.clustering import cancel_clustering_runs

    runs = ClusteringRun.objects.for_team(team_id).filter(status__in=ACTIVE_CLUSTERING_RUN_STATUSES)
    if job_id is not None:
        runs = runs.filter(job_id=job_id)
    ids = [str(run_id) for run_id in runs.values_list("id", flat=True)]
    runs.update(status=ClusteringRunStatus.CANCELED, finished_at=timezone.now(), updated_at=timezone.now())
    if ids:
        transaction.on_commit(lambda: cancel_clustering_runs.delay(team_id, ids), robust=True)
