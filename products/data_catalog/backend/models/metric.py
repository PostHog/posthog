from django.core.validators import RegexValidator
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDModel

from ..facade.enums import CreatedSource, MetricStatus

# A metric name is the SQL/API run handle (`information_schema.metrics.name`,
# `POST data_catalog/metrics/{name}/run`), so it must be a bare identifier.
METRIC_NAME_REGEX = r"^[A-Za-z][A-Za-z0-9_]*$"

validate_metric_name = RegexValidator(
    regex=METRIC_NAME_REGEX,
    message="Name must start with a letter and contain only letters, numbers, and underscores.",
)


class Metric(
    ModelActivityMixin, TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, DeletedMetaFields, UUIDModel
):
    """A canonical business metric: name + description, optionally a machine-readable definition.

    Names are reserved forever per team (the unique constraint is unconditional, soft-deleted rows
    keep their name), so a stored reference never silently points at a different metric. The state
    machine (proposed -> approved, drift) lives in ``logic/`` — ``status`` is never a writable
    serializer field.
    """

    # db_constraint=False on FKs to hot tables (posthog_team, posthog_user): a real FK constraint
    # takes SHARE ROW EXCLUSIVE on the parent, stalling writes under traffic. Scoping/integrity is
    # enforced at the app layer.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )

    name = models.CharField(
        max_length=128,
        validators=[validate_metric_name],
        help_text="Identifier-safe run handle, unique per team and reserved forever. Write-once.",
    )
    display_name = models.CharField(max_length=255, blank=True, help_text="Human-friendly label. Mutable, unlike name.")
    description = models.TextField(help_text="What the metric means and how to interpret it. The load-bearing text.")
    unit = models.CharField(max_length=64, blank=True, help_text="Unit of the result, e.g. usd, percent, cents.")
    owner = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
        help_text="The human accountable for this metric. AI generates, a human owns.",
    )

    definition = models.JSONField(
        null=True,
        blank=True,
        help_text="Machine-readable query (stored upgrade-canonical). Null means a name+description-only stub.",
    )
    referenced_table_names = models.JSONField(
        default=list,
        blank=True,
        help_text="Tables the definition directly references, extracted at write time for the catalog's denied-table filter.",
    )

    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in MetricStatus],
        default=MetricStatus.PROPOSED,
        help_text="Persisted lifecycle state. drifted is computed at read time, not stored here.",
    )
    approved_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    source_insight_short_id = models.CharField(
        max_length=12,
        null=True,
        blank=True,
        help_text="Short ID of the insight this metric was created from, for drift detection.",
    )
    source_insight_query_hash = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="Canonical hash of the insight query snapshot at create/refresh time.",
    )
    last_run_at = models.DateTimeField(
        null=True, blank=True, help_text="When the metric was last run (30-minute throttle)."
    )

    created_source = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in CreatedSource],
        default=CreatedSource.USER,
        help_text="Whether a human or an agent authored this metric.",
    )
    ai_model = models.CharField(
        max_length=128, blank=True, help_text="Model that generated the metric, if AI-authored."
    )
    confidence = models.FloatField(null=True, blank=True, help_text="AI author's confidence in the proposal, 0-1.")
    reasoning = models.TextField(blank=True, help_text="AI author's reasoning, surfaced as review context.")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="unique_metric_name_per_team"),
        ]
        indexes = [
            models.Index(fields=["team", "status"]),
            models.Index(fields=["team", "source_insight_short_id"]),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def definition_kind(self) -> str | None:
        """The query kind (HogQLQuery, TrendsQuery, ...), derived from the stored definition."""
        if not self.definition:
            return None
        return self.definition.get("kind")
