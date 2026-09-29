"""
Celery tasks for data_catalog.

Async entrypoints that call the logic layer.
Keep task functions thin - only call logic functions.
"""

from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.models.scoping import team_scope

from ..logic.lineage import sync_metric_lineage
from ..models.metric import Metric


@shared_task(
    name="posthog.tasks.data_catalog.sync_metric_lineage",
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
)
def sync_metric_lineage_task(metric_id: str, team_id: int) -> None:
    with team_scope(team_id):
        metric = Metric.objects.for_team(team_id).filter(pk=metric_id).select_related("team").first()
        if metric is None:
            return
        sync_metric_lineage(metric)
