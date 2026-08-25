from django.contrib import admin

from .models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchSuggestion,
    AutoresearchTrainingRun,
)


class AutoresearchModelInline(admin.TabularInline):
    model = AutoresearchModel
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("id", "role", "holdout_score", "realized_score", "is_preliminary", "created_at")
    readonly_fields = ("id", "role", "holdout_score", "realized_score", "is_preliminary", "created_at")


class AutoresearchTrainingRunInline(admin.TabularInline):
    model = AutoresearchTrainingRun
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("id", "status", "iteration_count", "best_holdout_score", "created_at")
    readonly_fields = ("id", "status", "iteration_count", "best_holdout_score", "created_at")


@admin.register(AutoresearchPipeline)
class AutoresearchPipelineAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "team",
        "target_event",
        "horizon_days",
        "status",
        "created_by",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("name", "target_event", "team__name")
    readonly_fields = ("id", "created_at", "updated_at", "last_scored_at")
    autocomplete_fields = ("team", "created_by")
    inlines = [AutoresearchModelInline, AutoresearchTrainingRunInline]

    fieldsets = (
        (None, {"fields": ("id", "name", "description", "status")}),
        ("Team & Owner", {"fields": ("team", "created_by")}),
        ("Prediction target", {"fields": ("target_event", "target_definition", "horizon_days")}),
        ("Population", {"fields": ("training_population", "inference_population")}),
        ("Output", {"fields": ("output_person_property",)}),
        ("Budget & schedule", {"fields": ("iteration_budget", "iteration_budget_remaining", "cadence_days")}),
        ("Stop criteria", {"fields": ("success_auc", "plateau_iterations")}),
        ("Dates", {"fields": ("created_at", "updated_at", "last_scored_at")}),
    )


class AutoresearchIterationInline(admin.TabularInline):
    model = AutoresearchIteration
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("iteration_number", "status", "holdout_score", "train_score", "agent_confidence", "created_at")
    readonly_fields = ("iteration_number", "status", "holdout_score", "train_score", "agent_confidence", "created_at")


@admin.register(AutoresearchTrainingRun)
class AutoresearchTrainingRunAdmin(admin.ModelAdmin):
    list_display = ("id", "pipeline", "status", "iteration_count", "best_holdout_score", "task_run_id", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("pipeline__name",)
    readonly_fields = ("id", "created_at", "started_at", "completed_at")
    raw_id_fields = ("pipeline",)
    inlines = [AutoresearchIterationInline]

    fieldsets = (
        (None, {"fields": ("id", "pipeline", "status")}),
        ("Task sandbox", {"fields": ("task_run_id",)}),
        ("Progress", {"fields": ("iteration_budget", "iteration_count", "best_holdout_score")}),
        ("Error", {"fields": ("error",)}),
        ("Dates", {"fields": ("created_at", "started_at", "completed_at")}),
    )


@admin.register(AutoresearchModel)
class AutoresearchModelAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "pipeline",
        "role",
        "holdout_score",
        "realized_score",
        "is_preliminary",
        "recipe_hash",
        "created_at",
    )
    list_filter = ("role", "is_preliminary", "created_at")
    search_fields = ("pipeline__name", "recipe_hash", "agent_description")
    readonly_fields = ("id", "recipe_hash", "created_at", "updated_at", "promoted_at", "archived_at")
    raw_id_fields = ("pipeline", "source_training_run")

    fieldsets = (
        (None, {"fields": ("id", "pipeline", "role", "is_preliminary")}),
        ("Recipe", {"fields": ("recipe_hash", "model_recipe", "model_explanation")}),
        ("Performance", {"fields": ("holdout_score", "realized_score", "calibration_error", "metrics")}),
        ("Provenance", {"fields": ("source_training_run", "agent_description", "trained_on_start", "trained_on_end")}),
        ("Dates", {"fields": ("created_at", "updated_at", "promoted_at", "archived_at")}),
    )


@admin.register(AutoresearchRun)
class AutoresearchRunAdmin(admin.ModelAdmin):
    list_display = ("id", "pipeline", "run_type", "status", "rows_scored", "created_at")
    list_filter = ("run_type", "status", "created_at")
    search_fields = ("pipeline__name",)
    readonly_fields = ("id", "created_at", "started_at", "completed_at")
    raw_id_fields = ("pipeline", "model")

    fieldsets = (
        (None, {"fields": ("id", "pipeline", "model", "run_type", "status")}),
        ("Results", {"fields": ("rows_scored", "metrics")}),
        ("Error", {"fields": ("error",)}),
        ("Dates", {"fields": ("created_at", "started_at", "completed_at")}),
    )


@admin.register(AutoresearchSuggestion)
class AutoresearchSuggestionAdmin(admin.ModelAdmin):
    list_display = ("id", "pipeline", "priority", "status", "source", "created_by", "created_at")
    list_filter = ("priority", "status", "source", "created_at")
    search_fields = ("pipeline__name", "prompt")
    readonly_fields = ("id", "created_at", "updated_at")
    raw_id_fields = ("pipeline", "created_by")

    fieldsets = (
        (None, {"fields": ("id", "pipeline", "created_by", "source")}),
        ("Content", {"fields": ("prompt", "priority", "status")}),
        ("Agent response", {"fields": ("agent_response",)}),
        ("Dates", {"fields": ("created_at", "updated_at")}),
    )
