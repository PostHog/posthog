from datetime import timedelta

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from ..facade.clustering_contracts import ClusteringRunRef
from ..logic.clustering.runs import get_run_context
from ..models.clustering_run import ACTIVE_CLUSTERING_RUN_STATUSES, ClusteringRun, ClusteringRunStatus
from ..temporal.clustering_client import dispatch_clustering_run, reconcile_clustering_run

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, soft_time_limit=20, time_limit=30)
def start_clustering_run(team_id: int, run_id: str) -> None:
    run = ClusteringRun.objects.for_team(team_id).filter(id=run_id).first()
    if run is None:
        return
    context = get_run_context(ClusteringRunRef(team_id=team_id, run_id=run_id))
    if context is not None and context.active:
        if run.status == ClusteringRunStatus.QUEUED and run.is_first_run:
            dispatch_clustering_run(team_id, run_id)
        else:
            reconcile_clustering_run(team_id, run_id, run.workflow_id)
    else:
        cancel_clustering_runs(team_id, [run_id])


@shared_task(ignore_result=True, soft_time_limit=20, time_limit=30)
def cancel_clustering_runs(team_id: int, run_ids: list[str]) -> None:
    for run in ClusteringRun.objects.for_team(team_id).filter(id__in=run_ids, status=ClusteringRunStatus.CANCELED):
        reconcile_clustering_run(team_id, str(run.id), run.workflow_id, cancel=True)
        ClusteringRun.objects.for_team(team_id).filter(id=run.id).update(last_dispatch_at=timezone.now())


@shared_task(ignore_result=True, soft_time_limit=20, time_limit=30)
@skip_team_scope_audit
def dispatch_queued_clustering_runs() -> None:
    now = timezone.now()
    with transaction.atomic():
        runs = list(
            ClusteringRun.objects.unscoped()
            .select_for_update(skip_locked=True)
            .filter(
                Q(status__in=ACTIVE_CLUSTERING_RUN_STATUSES)
                & (Q(last_dispatch_at__isnull=True) | Q(last_dispatch_at__lt=now - timedelta(minutes=1)))
                | Q(status=ClusteringRunStatus.CANCELED)
                & (Q(last_dispatch_at__isnull=True) | Q(last_dispatch_at__lt=F("finished_at")))
            )
            .order_by("last_dispatch_at", "created_at")[:100]
        )
        ClusteringRun.objects.unscoped().filter(
            id__in=[run.id for run in runs], status__in=ACTIVE_CLUSTERING_RUN_STATUSES
        ).update(last_dispatch_at=now)
    for run in runs:
        try:
            start_clustering_run.apply_async(args=[run.team_id, str(run.id)], retry=False, expires=60)
        except Exception:
            logger.exception("clustering_run_enqueue_failed", run_id=str(run.id), team_id=run.team_id)
