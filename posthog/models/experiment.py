from django.db import models
from django.utils import timezone


class Experiment(models.Model):
    class ExperimentType(models.TextChoices):
        WEB = "web", "web"
        PRODUCT = "product", "product"

    name = models.CharField(max_length=400)
    description = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    # Filters define the target metric of an Experiment
    filters = models.JSONField(default=dict)

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
    secondary_metrics = models.JSONField(default=list, null=True)

    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True)
    feature_flag = models.ForeignKey("FeatureFlag", blank=False, on_delete=models.RESTRICT)
    exposure_cohort = models.ForeignKey("Cohort", on_delete=models.SET_NULL, null=True)
    holdout = models.ForeignKey("ExperimentHoldout", on_delete=models.SET_NULL, null=True)

    start_date = models.DateTimeField(null=True)
    end_date = models.DateTimeField(null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    archived = models.BooleanField(default=False)
    type = models.CharField(max_length=40, choices=ExperimentType.choices, null=True, blank=True, default="product")
    variants = models.JSONField(default=dict, null=True, blank=True)

    metrics = models.JSONField(default=list, null=True, blank=True)
    saved_metrics = models.ManyToManyField(
        "ExperimentSavedMetric", blank=True, related_name="experiments", through="ExperimentToSavedMetric"
    )

    def get_feature_flag_key(self):
        return self.feature_flag.key

    @property
    def is_draft(self):
        return not self.start_date


class ExperimentHoldout(models.Model):
    name = models.CharField(max_length=400)
    description = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    # Filters define the definition of the holdout
    # This is then replicated across flags for experiments in the holdout
    filters = models.JSONField(default=list)

    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)


class ExperimentSavedMetric(models.Model):
    name = models.CharField(max_length=400)
    description = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    query = models.JSONField()

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
