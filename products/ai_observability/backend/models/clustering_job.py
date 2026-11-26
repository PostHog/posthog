from django.db import models

from posthog.models.utils import UUIDModel


class ClusteringAnalysisLevel(models.TextChoices):
    TRACE = "trace", "trace"
    GENERATION = "generation", "generation"
    EVALUATION = "evaluation", "evaluation"


class ClusteringJob(UUIDModel):
    """A named clustering configuration for a team.

    Each job defines one analysis level (trace, generation, or evaluation) and one set of
    event filters.  A team may have up to MAX_JOBS_PER_TEAM jobs (see api.clustering_job).
    """

    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="clustering_jobs",
    )
    name = models.CharField(max_length=100)
    analysis_level = models.CharField(
        max_length=20,
        choices=ClusteringAnalysisLevel.choices,
    )
    event_filters = models.JSONField(default=list, blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "llm_analytics_clusteringjob"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                name="unique_clustering_job_name_per_team",
            ),
        ]

    def __str__(self) -> str:
        return f"ClusteringJob(team={self.team_id}, name={self.name!r}, level={self.analysis_level})"


DEFAULT_LEVEL_SPECS = (
    ("Default - traces", "trace"),
    ("Default - generations", "generation"),
    ("Default - evaluations", "evaluation"),
)
