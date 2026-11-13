from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class ClusteringRunStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    WAITING = "waiting", "Waiting for data"
    PREPARING = "preparing", "Preparing data"
    CLUSTERING = "clustering", "Finding clusters"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELED = "canceled", "Stopped"


ACTIVE_CLUSTERING_RUN_STATUSES = (
    ClusteringRunStatus.QUEUED,
    ClusteringRunStatus.WAITING,
    ClusteringRunStatus.PREPARING,
    ClusteringRunStatus.CLUSTERING,
)


class ClusteringRun(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    job = models.ForeignKey("ai_observability.ClusteringJob", on_delete=models.CASCADE, related_name="first_runs")
    workflow_id = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=20, choices=ClusteringRunStatus.choices, default=ClusteringRunStatus.QUEUED)
    eligible_count = models.PositiveIntegerField(null=True)
    prepared_count = models.PositiveIntegerField(default=0)
    cluster_count = models.PositiveIntegerField(null=True)
    failure_reason = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["job"],
                condition=models.Q(status__in=ACTIVE_CLUSTERING_RUN_STATUSES),
                name="aio_one_active_clustering_run",
            )
        ]
