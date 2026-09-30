from django import forms
from django.contrib import admin

from products.experiments.backend.models.team_experiments_config import (
    TeamExperimentsConfig,
    legacy_from_recalculation_times,
    recalculation_times_from_legacy,
)


class TeamExperimentsConfigInlineForm(forms.ModelForm):
    def save(self, commit: bool = True) -> TeamExperimentsConfig:
        # A human toggling precomputation must stick: the auto-enrollment job only
        # writes when precomputation_enabled_set_by is null or "auto".
        if "experiment_precomputation_enabled" in self.changed_data:
            self.instance.precomputation_enabled_set_by = TeamExperimentsConfig.PrecomputationEnabledSetBy.MANUAL
        # The two recalculation fields must stay coherent while both exist: writing one
        # syncs the other, matching the experiments_config serializer.
        if "experiment_recalculation_times" in self.changed_data:
            self.instance.experiment_recalculation_times = self.instance.experiment_recalculation_times or None
            self.instance.experiment_recalculation_time = legacy_from_recalculation_times(
                self.instance.experiment_recalculation_times
            )
        elif "experiment_recalculation_time" in self.changed_data:
            self.instance.experiment_recalculation_times = recalculation_times_from_legacy(
                self.instance.experiment_recalculation_time
            )
        return super().save(commit)


class TeamExperimentsConfigInline(admin.StackedInline):
    model = TeamExperimentsConfig
    form = TeamExperimentsConfigInlineForm
    extra = 0
    max_num = 1
    classes = ("collapse",)

    fieldsets = [
        (
            "Experiments",
            {
                "fields": [
                    "experiment_recalculation_time",
                    "experiment_recalculation_times",
                    "default_experiment_confidence_level",
                    "default_experiment_stats_method",
                    "experiment_precomputation_enabled",
                    "default_only_count_matured_users",
                    "default_cuped_enabled",
                    "default_cuped_lookback_days",
                    "default_sequential_testing_enabled",
                    "default_sequential_tuning_parameter",
                ],
            },
        ),
    ]

    def has_delete_permission(self, request, obj=None):
        return False
