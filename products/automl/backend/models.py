"""
Django models for AutoML.

Keep models thin — business logic belongs in logic/.
Use types from facade/enums.py for choices where applicable.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.
"""

from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import uuid7

from .facade.enums import AutonomyLevel, Cadence, PipelineStatus, TaskType


class AutoMLPipeline(ProductTeamModel):
    """A user-configured AutoML pipeline.

    Stores the durable config plus high-level status. Task-type-specific
    config lives in ``config`` as JSON for now; the IO contract in the
    ``automl`` design skill (``io-spec.md``) describes the per-task shape.
    We may break out typed columns once the contract is exercised.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)

    name = models.CharField(
        max_length=255,
        help_text="Human-readable pipeline name. Unique within the team.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Free-form description for the pipeline detail page.",
    )

    task_type = models.CharField(
        max_length=32,
        choices=[(t.value, t.value) for t in TaskType],
        help_text="One of clustering / classification / regression / forecasting.",
    )
    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in PipelineStatus],
        default=PipelineStatus.DRAFT.value,
        help_text="Lifecycle state of the pipeline.",
    )
    autonomy = models.CharField(
        max_length=32,
        choices=[(a.value, a.value) for a in AutonomyLevel],
        default=AutonomyLevel.CHAMPION_ONLY.value,
        help_text="Output autonomy gate: shadow_only / champion_only / promote_eligible.",
    )

    config = models.JSONField(
        default=dict,
        help_text="Task-type-specific configuration (target, horizon, cluster_count, etc.).",
    )
    training_population = models.JSONField(
        default=dict,
        help_text='Population definition for training, e.g. {"kind": "hogql", "query": "..."}.',
    )
    inference_population = models.JSONField(
        default=dict,
        help_text="Population definition for scheduled inference.",
    )

    inference_cadence = models.CharField(
        max_length=16,
        choices=[(c.value, c.value) for c in Cadence],
        default=Cadence.DAILY.value,
        help_text="How often the inference workflow runs.",
    )
    retraining_cadence = models.CharField(
        max_length=16,
        choices=[(c.value, c.value) for c in Cadence],
        default=Cadence.DAILY.value,
        help_text="How often the model is refit on a rolling window.",
    )

    output_property_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Person/group property name to write the latest prediction to.",
    )

    runtime = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "System-managed runtime state. Holds pointers like the bootstrap task id, "
            "champion mlflow run id, and last inference timestamp. Distinct from user-"
            "configured `config` so we never overwrite user intent with system state."
        ),
    )

    # Plain integer instead of FK — keeps us free to move products to separate
    # databases later without rewriting (per products/architecture.md).
    created_by_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="ID of the user who created the pipeline.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["team_id", "name"],
                name="automl_pipeline_team_name_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["team_id", "status"]),
            models.Index(fields=["team_id", "task_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.task_type})"
