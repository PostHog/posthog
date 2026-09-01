from django.contrib import admin
from django.db import models
from django.http import HttpRequest

from .models import (
    AutoresearchIteration,
    AutoresearchModel,
    AutoresearchPipeline,
    AutoresearchRun,
    AutoresearchSuggestion,
    AutoresearchTrainingRun,
)


class PipelineLockedAdminMixin(admin.ModelAdmin):
    """Makes `pipeline` read-only once the row exists.

    Rows that reference this one check same-pipeline consistency only on their own save,
    so moving a saved row to another pipeline would strand its referencing rows under the
    old pipeline and team.
    """

    def get_readonly_fields(self, request: HttpRequest, obj: models.Model | None = None) -> tuple[str, ...]:
        readonly = super().get_readonly_fields(request, obj)
        if obj is not None:
            return (*readonly, "pipeline")
        return tuple(readonly)


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
        (
            "Prediction target",
            {"fields": ("target_event", "target_definition", "horizon_days", "training_lookback_days")},
        ),
        ("Population", {"fields": ("training_population", "inference_population")}),
        ("Output", {"fields": ("output_person_property",)}),
        ("Budget & schedule", {"fields": ("iteration_budget", "iteration_budget_remaining", "cadence_days")}),
        ("Stop criteria", {"fields": ("success_auc", "plateau_iterations")}),
        ("Dates", {"fields": ("created_at", "updated_at", "last_scored_at")}),
    )

    def get_readonly_fields(self, request: HttpRequest, obj: AutoresearchPipeline | None = None) -> tuple[str, ...]:
        # Every child row copies team_id from the pipeline at save time. Moving a saved
        # pipeline to another team would strand those copies under the old tenant.
        if obj is not None:
            return (*self.readonly_fields, "team")
        return self.readonly_fields


class AutoresearchIterationInline(admin.TabularInline):
    model = AutoresearchIteration
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("iteration_number", "status", "holdout_score", "train_score", "agent_confidence", "created_at")
    readonly_fields = ("iteration_number", "status", "holdout_score", "train_score", "agent_confidence", "created_at")


@admin.register(AutoresearchTrainingRun)
class AutoresearchTrainingRunAdmin(PipelineLockedAdminMixin):
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
class AutoresearchModelAdmin(PipelineLockedAdminMixin):
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
    # model_recipe is readonly because recipe_hash is its SHA-256; an admin edit to one
    # without the other would break hash-based dedup and provenance.
    readonly_fields = (
        "id",
        "recipe_hash",
        "model_recipe",
        "artifact_prefix",
        "created_at",
        "updated_at",
        "promoted_at",
        "archived_at",
    )
    raw_id_fields = ("pipeline", "source_training_run")

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Models are created by the training loop and promotion. The add form excludes the
        # read-only model_recipe, so a hand-created row would fail its NOT NULL constraint.
        return False

    fieldsets = (
        (None, {"fields": ("id", "pipeline", "role", "is_preliminary")}),
        ("Recipe", {"fields": ("recipe_hash", "model_recipe", "artifact_prefix", "model_explanation")}),
        ("Performance", {"fields": ("holdout_score", "realized_score", "calibration_error", "metrics")}),
        ("Provenance", {"fields": ("source_training_run", "agent_description", "trained_on_start", "trained_on_end")}),
        ("Dates", {"fields": ("created_at", "updated_at", "promoted_at", "archived_at")}),
    )


@admin.register(AutoresearchIteration)
class AutoresearchIterationAdmin(admin.ModelAdmin):
    """Read-only detail view behind the training-run inline's change links."""

    list_display = ("id", "training_run", "iteration_number", "status", "holdout_score", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("pipeline__name", "recipe_hash")
    raw_id_fields = ("pipeline", "training_run", "parent_suggestion")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: AutoresearchIteration | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: AutoresearchIteration | None = None) -> bool:
        return False


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
class AutoresearchSuggestionAdmin(PipelineLockedAdminMixin):
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
