
from django.db import models
from django.utils import timezone


class Experiment(models.Model):
    name: models.CharField = models.CharField(max_length=400)
    description: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)

    # Filters define the target metric of an Experiment
    filters: models.JSONField = models.JSONField(default=dict)

    # Parameters include configuration fields for the experiment: What the control & test variant are called,
    # and any test significance calculation parameters
    # We have 4 parameters today:
    #   minimum_detectable_effect: number
    #   recommended_running_time: number
    #   recommended_sample_size: number
    #   feature_flag_variants: { key: string, name: string, rollout_percentage: number }[]
    #   custom_exposure_filter: Filter json
    parameters: models.JSONField = models.JSONField(default=dict, null=True)

    # A list of filters for secondary metrics
    secondary_metrics: models.JSONField = models.JSONField(default=list, null=True)

    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True)
    feature_flag: models.ForeignKey = models.ForeignKey("FeatureFlag", blank=False, on_delete=models.RESTRICT)
    exposure_cohort: models.ForeignKey = models.ForeignKey("Cohort", on_delete=models.SET_NULL, null=True)
    start_date: models.DateTimeField = models.DateTimeField(null=True)
    end_date: models.DateTimeField = models.DateTimeField(null=True)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    archived: models.BooleanField = models.BooleanField(default=False)

    def get_feature_flag_key(self):
        return self.feature_flag.key

    @property
    def is_draft(self):
        return not self.start_date

    @property
    def variants(self):
        return None
