from typing import TYPE_CHECKING, Any

from django.db import models
from django.db.models import QuerySet
from django.utils import timezone

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.utils import RootTeamMixin, UUIDModel

if TYPE_CHECKING:
    from posthog.models.team import Team


class Experiment(FileSystemSyncMixin, ModelActivityMixin, RootTeamMixin, models.Model):
    class ExperimentType(models.TextChoices):
        WEB = "web", "web"
        PRODUCT = "product", "product"

    name = models.CharField(max_length=400)
    description = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    # Filters define the target metric of an Experiment
    filters = models.JSONField(default=dict, blank=True)

    # Parameters include configuration fields for the experiment: What the control & test variant are called,
    # and any test significance calculation parameters
    # We have 4 parameters today:
    #   minimum_detectable_effect: number
    #   recommended_running_time: number
    #   recommended_sample_size: number
    #   feature_flag_variants: { key: string, name: string, rollout_percentage: number }[]
    #   custom_exposure_filter: Filter json
    parameters = models.JSONField(default=dict, null=True)

    # A list of filters for secondary metrics
    secondary_metrics = models.JSONField(default=list, null=True, blank=True)

    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True)
    feature_flag = models.ForeignKey("FeatureFlag", blank=False, on_delete=models.RESTRICT)
    exposure_cohort = models.ForeignKey("Cohort", on_delete=models.SET_NULL, null=True, blank=True)
    holdout = models.ForeignKey("ExperimentHoldout", on_delete=models.SET_NULL, null=True, blank=True)

    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    archived = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False, null=True)
    type = models.CharField(max_length=40, choices=ExperimentType.choices, null=True, blank=True, default="product")
    variants = models.JSONField(default=dict, null=True, blank=True)

    exposure_criteria = models.JSONField(default=dict, null=True, blank=True)

    metrics = models.JSONField(default=list, null=True, blank=True)
    metrics_secondary = models.JSONField(default=list, null=True, blank=True)
    primary_metrics_ordered_uuids = models.JSONField(default=None, null=True, blank=True)
    secondary_metrics_ordered_uuids = models.JSONField(default=None, null=True, blank=True)
    saved_metrics: models.ManyToManyField = models.ManyToManyField(
        "ExperimentSavedMetric", blank=True, related_name="experiments", through="ExperimentToSavedMetric"
    )

    stats_config = models.JSONField(default=dict, null=True, blank=True)

    conclusion = models.CharField(
        max_length=30,
        choices=[
            ("won", "Won"),
            ("lost", "Lost"),
            ("inconclusive", "Inconclusive"),
            ("stopped_early", "Stopped Early"),
            ("invalid", "Invalid"),
        ],
        null=True,
        blank=True,
    )
    conclusion_comment = models.TextField(
        null=True,
        blank=True,
    )

    def __str__(self):
        return self.name or "Untitled"

    def get_feature_flag_key(self):
        return self.feature_flag.key

    def get_stats_config(self, key: str):
        return self.stats_config.get(key) if self.stats_config else None

    @property
    def is_draft(self):
        return not self.start_date

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet["Experiment"]:
        base_qs = cls.objects.filter(team=team).exclude(deleted=True)
        return cls._filter_unfiled_queryset(base_qs, team, type="experiment", ref_field="id")

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Experiments"),
            type="experiment",  # sync with APIScopeObject in scopes.py
            ref=str(self.id),
            name=self.name or "Untitled",
            href=f"/experiments/{self.id}",
            meta={
                "created_at": str(self.created_at),
                "created_by": self.created_by_id,
            },
            should_delete=False,  # always keep in FileSystem
        )


class ExperimentHoldout(ModelActivityMixin, RootTeamMixin, models.Model):
    name = models.CharField(max_length=400)
    description = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    # Filters define the definition of the holdout
    # This is then replicated across flags for experiments in the holdout
    filters = models.JSONField(default=list)

    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args: Any, skip_activity_log: bool = False, **kwargs: Any) -> None:
        if skip_activity_log:
            # Bypass ModelActivityMixin.save() and call Model.save() directly
            super(ModelActivityMixin, self).save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


class ExperimentSavedMetric(ModelActivityMixin, RootTeamMixin, models.Model):
    name = models.CharField(max_length=400)
    description = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    query = models.JSONField()

    # Metadata for the saved metric
    # has things like if this metric was migrated from a legacy metric
    metadata = models.JSONField(null=True, blank=True, default=dict)

    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)


class ExperimentToSavedMetric(models.Model):
    experiment = models.ForeignKey("Experiment", on_delete=models.CASCADE)
    saved_metric = models.ForeignKey("ExperimentSavedMetric", on_delete=models.CASCADE)

    # Metadata for the saved metric at the time of the experiment creation
    # has stuff like whether this metric is primary, and any other information
    # we need for the metric, other than the query.
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.experiment.name} - {self.saved_metric.name} - {self.metadata}"


class ExperimentMetricResult(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    experiment = models.ForeignKey("Experiment", on_delete=models.CASCADE)
    metric_uuid = models.CharField(max_length=255)
    fingerprint = models.CharField(max_length=64, null=True, blank=True)  # SHA256 hash is 64 chars
    query_from = models.DateTimeField()
    query_to = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    result = models.JSONField(null=True, blank=True, default=None)
    query_id = models.CharField(max_length=255, null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["experiment", "metric_uuid", "query_to"]
        indexes = [
            models.Index(fields=["experiment", "metric_uuid", "query_to"]),
        ]

    def __str__(self):
        return f"ExperimentMetricResult({self.experiment_id}, {self.metric_uuid}, {self.query_from}, {self.status})"


class ExperimentTimeseriesRecalculation(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    experiment = models.ForeignKey("Experiment", on_delete=models.CASCADE)
    metric = models.JSONField()
    fingerprint = models.CharField(max_length=64)  # SHA256 hash

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    last_successful_date = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["experiment", "fingerprint"],
                condition=models.Q(status__in=["pending", "in_progress"]),
                name="unique_active_recalculation_per_experiment_metric",
            ),
        ]

    def __str__(self):
        metric_uuid = self.metric.get("uuid", "unknown")
        return f"ExperimentTimeseriesRecalculation(exp={self.experiment_id}, metric={metric_uuid}, fingerprint={self.fingerprint}, status={self.status})"
