from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.forms import ModelForm

from posthog.models import Experiment, Cohort, ExperimentHoldout, FeatureFlag


class ExperimentAdminForm(ModelForm):
    class Meta:
        model = Experiment
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit the queryset of the exposure_cohort and holdout fields to the team
        # Otherwise, the queryset will fetch _all_ cohorts and holdouts for _all_ teams,
        # which is a lot and quite slow.
        if self.instance and self.instance.pk:
            if "exposure_cohort" in self.fields:
                self.fields["exposure_cohort"].queryset = Cohort.objects.filter(team=self.instance.team)  # type: ignore
            if "holdout" in self.fields:
                self.fields["holdout"].queryset = ExperimentHoldout.objects.filter(team=self.instance.team)  # type: ignore
            if "feature_flag" in self.fields:
                self.fields["feature_flag"].queryset = FeatureFlag.objects.filter(team=self.instance.team)  # type: ignore


class ExperimentAdmin(admin.ModelAdmin):
    form = ExperimentAdminForm
    list_display = (
        "id",
        "name",
        "team_link",
        "created_at",
        "created_by",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team", "created_by")
    ordering = ("-created_at",)

    @admin.display(description="Team")
    def team_link(self, experiment: Experiment):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[experiment.team.pk]),
            experiment.team.name,
        )
