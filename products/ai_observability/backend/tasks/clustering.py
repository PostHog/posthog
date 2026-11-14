from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from ..facade.clustering_contracts import ClusteringRunRef
from ..logic.clustering.runs import get_run_context
from ..models.clustering_run import ClusteringRun, ClusteringRunStatus
from ..temporal.clustering_client import dispatch_clustering_run

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, soft_time_limit=20, time_limit=30)
def start_clustering_run(team_id: int, run_id: str) -> None:
    context = get_run_context(ClusteringRunRef(team_id=team_id, run_id=run_id))
    if context is not None and context.active:
        dispatch_clustering_run(team_id, run_id)


@shared_task(ignore_result=True, soft_time_limit=20, time_limit=30)
@skip_team_scope_audit
def dispatch_queued_clustering_runs() -> None:
    now = timezone.now()
    with transaction.atomic():
        runs = list(
            ClusteringRun.objects.unscoped()
            .select_for_update(skip_locked=True)
            .filter(status=ClusteringRunStatus.QUEUED)
            .filter(Q(last_dispatch_at__isnull=True) | Q(last_dispatch_at__lt=now - timedelta(minutes=1)))
            .order_by("last_dispatch_at", "created_at")[:100]
        )
        ClusteringRun.objects.unscoped().filter(id__in=[run.id for run in runs]).update(last_dispatch_at=now)
    for run in runs:
        try:
            start_clustering_run.apply_async(args=[run.team_id, str(run.id)], retry=False, expires=60)
        except Exception:
            logger.exception("clustering_run_enqueue_failed", run_id=str(run.id), team_id=run.team_id)
