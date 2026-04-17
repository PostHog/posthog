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
                ],
            },
        ),
    ]

    def has_delete_permission(self, request, obj=None):
        return False
