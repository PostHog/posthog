from django.contrib import admin

from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig


class TeamExperimentsConfigInline(admin.StackedInline):
    model = TeamExperimentsConfig
    extra = 0
    max_num = 1
    classes = ("collapse",)

    fieldsets = [
        (
            "Experiments",
            {
                "fields": [
                    "experiment_recalculation_time",
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
