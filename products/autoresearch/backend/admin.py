from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest

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

    # Admin has no ambient team scope and _default_manager here is the fail-closed
    # manager, so the cross-team queryset has to be asked for explicitly.
    def get_queryset(self, request: HttpRequest) -> QuerySet[AutoresearchModel]:
        return AutoresearchModel.objects.unscoped()


class AutoresearchTrainingRunInline(admin.TabularInline):
    model = AutoresearchTrainingRun
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("id", "status", "iteration_count", "best_holdout_score", "created_at")
    readonly_fields = ("id", "status", "iteration_count", "best_holdout_score", "created_at")

    # Admin has no ambient team scope and _default_manager here is the fail-closed
    # manager, so the cross-team queryset has to be asked for explicitly.
    def get_queryset(self, request: HttpRequest) -> QuerySet[AutoresearchTrainingRun]:
        return AutoresearchTrainingRun.objects.unscoped()


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

    # Admin has no ambient team scope and _default_manager here is the fail-closed
    # manager, so the cross-team queryset has to be asked for explicitly.
    def get_queryset(self, request: HttpRequest) -> QuerySet[AutoresearchPipeline]:
        return AutoresearchPipeline.objects.unscoped()


class AutoresearchIterationInline(admin.TabularInline):
    model = AutoresearchIteration
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("iteration_number", "status", "holdout_score", "train_score", "agent_confidence", "created_at")
    readonly_fields = ("iteration_number", "status", "holdout_score", "train_score", "agent_confidence", "created_at")

    # Admin has no ambient team scope and _default_manager here is the fail-closed
    # manager, so the cross-team queryset has to be asked for explicitly.
    def get_queryset(self, request: HttpRequest) -> QuerySet[AutoresearchIteration]:
        return AutoresearchIteration.objects.unscoped()


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

    # Admin has no ambient team scope and _default_manager here is the fail-closed
    # manager, so the cross-team queryset has to be asked for explicitly.
    def get_queryset(self, request: HttpRequest) -> QuerySet[AutoresearchTrainingRun]:
        return AutoresearchTrainingRun.objects.unscoped()


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
    # recipe_hash is the SHA-256 of model_recipe, and nothing here recomputes it, so an
    # edited recipe would keep the old hash and a hand-created row would have none at all.
    # Models are written by the training loop; admin reads them.
    readonly_fields = (
        "id",
        "recipe_hash",
        "model_recipe",
        "created_at",
        "updated_at",
        "promoted_at",
        "archived_at",
    )
    raw_id_fields = ("pipeline", "source_training_run")

    fieldsets = (
        (None, {"fields": ("id", "pipeline", "role", "is_preliminary")}),
        ("Recipe", {"fields": ("recipe_hash", "model_recipe", "model_explanation")}),
        ("Performance", {"fields": ("holdout_score", "realized_score", "calibration_error", "metrics")}),
        ("Provenance", {"fields": ("source_training_run", "agent_description", "trained_on_start", "trained_on_end")}),
        ("Dates", {"fields": ("created_at", "updated_at", "promoted_at", "archived_at")}),
    )

    # Admin has no ambient team scope and _default_manager here is the fail-closed
    # manager, so the cross-team queryset has to be asked for explicitly.
    def get_queryset(self, request: HttpRequest) -> QuerySet[AutoresearchModel]:
        return AutoresearchModel.objects.unscoped()

    def has_add_permission(self, request: HttpRequest) -> bool:
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

    # Admin has no ambient team scope and _default_manager here is the fail-closed
    # manager, so the cross-team queryset has to be asked for explicitly.
    def get_queryset(self, request: HttpRequest) -> QuerySet[AutoresearchRun]:
        return AutoresearchRun.objects.unscoped()


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

    # Admin has no ambient team scope and _default_manager here is the fail-closed
    # manager, so the cross-team queryset has to be asked for explicitly.
    def get_queryset(self, request: HttpRequest) -> QuerySet[AutoresearchSuggestion]:
        return AutoresearchSuggestion.objects.unscoped()


@admin.register(AutoresearchIteration)
class AutoresearchIterationAdmin(admin.ModelAdmin):
    """Read-only: iterations are written by the training loop, never by hand."""

    list_display = ("id", "pipeline", "training_run", "iteration_number", "status", "holdout_score", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("pipeline__name", "recipe_hash")
    raw_id_fields = ("pipeline", "training_run", "parent_suggestion")
    readonly_fields = (
        "id",
        "pipeline",
        "training_run",
        "iteration_number",
        "recipe_hash",
        "recipe_snapshot",
        "model_spec",
        "train_score",
        "holdout_score",
        "status",
        "agent_description",
        "agent_confidence",
        "parent_suggestion",
        "created_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: AutoresearchIteration | None = None) -> bool:
        return False

    # Admin has no ambient team scope and _default_manager here is the fail-closed
    # manager, so the cross-team queryset has to be asked for explicitly.
    def get_queryset(self, request: HttpRequest) -> QuerySet[AutoresearchIteration]:
        return AutoresearchIteration.objects.unscoped()
