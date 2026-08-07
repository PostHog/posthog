from django.core.validators import RegexValidator
from django.db import models

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDModel

from ..facade.enums import CheckRunStatus, CheckSeverity, CheckType, CreatedSource, SubjectStatus, SubjectType

# A check name is an addressable handle in `information_schema.data_quality_checks` and in agent
# prose, so it follows the same bare-identifier discipline as a metric name.
CHECK_NAME_REGEX = r"^[A-Za-z][A-Za-z0-9_]*$"

validate_check_name = RegexValidator(
    regex=CHECK_NAME_REGEX,
    message="Name must start with a letter and contain only letters, numbers, and underscores.",
)


class DataQualityCheck(
    ModelActivityMixin, TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, DeletedMetaFields, UUIDModel
):
    """An assertion about a warehouse table or view, in the ``dbt test`` sense.

    A check passes when its compiled query finds zero failing rows. The definition is the source of
    truth here; ``fingerprint`` makes agent authoring idempotent (re-creating a semantically
    identical check upserts instead of duplicating), and it is also the stable identity a git-synced
    config file would round-trip against.

    ``last_status`` / ``last_run_at`` are denormalized from the newest ``DataQualityCheckRun`` so
    per-subject health is a single indexed read rather than a correlated subquery over run history.
    """

    # db_constraint=False on FKs to hot tables (posthog_team, posthog_user): a real FK constraint
    # takes SHARE ROW EXCLUSIVE on the parent, stalling writes under traffic. Scoping/integrity is
    # enforced at the app layer.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    owner = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
        help_text="The human accountable for this check. AI generates, a human owns.",
    )

    name = models.CharField(
        max_length=128,
        blank=True,
        validators=[validate_check_name],
        help_text="Optional identifier-safe handle, unique per team when set. Blank means address the check by id.",
    )
    description = models.TextField(blank=True, help_text="Why this check exists and what a failure means.")

    subject_type = models.CharField(
        max_length=32,
        choices=[(t.value, t.value) for t in SubjectType],
        help_text="Kind of catalog object being checked: table or view.",
    )
    subject_uuid = models.UUIDField(help_text="Id of the subject in its owning product. Not a foreign key.")
    subject_name = models.CharField(
        max_length=400,
        help_text="Queryable name of the subject, refreshed on every run so renames self-heal.",
    )
    subject_status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in SubjectStatus],
        default=SubjectStatus.ACTIVE,
        help_text="orphaned once the subject stops resolving; orphaned checks are skipped, not deleted.",
    )
    column_name = models.CharField(
        max_length=400,
        blank=True,
        help_text="Column the check applies to. Blank for table-scoped types like row_count.",
    )

    check_type = models.CharField(
        max_length=32,
        choices=[(t.value, t.value) for t in CheckType],
        help_text="Which assertion to make. Determines the shape of config.",
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Type-specific configuration, validated against the check type's JSON schema.",
    )
    severity = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in CheckSeverity],
        default=CheckSeverity.ERROR,
        help_text="error failures mark the subject failing and notify; warn failures only surface.",
    )
    enabled = models.BooleanField(default=True, help_text="Disabled checks are never run by any trigger.")
    tags = models.JSONField(default=list, blank=True, help_text="Free-form labels for grouping and filtering.")

    run_on_materialization = models.BooleanField(
        default=True,
        help_text="Run this check after its view materializes. Never delays or fails the materialization.",
    )
    schedule_interval_minutes = models.IntegerField(
        null=True,
        blank=True,
        help_text="Independent cadence in minutes. Null means no schedule of its own.",
    )
    next_run_at = models.DateTimeField(
        null=True, blank=True, help_text="When the due-checks scanner should next pick this check up."
    )

    last_run_at = models.DateTimeField(null=True, blank=True, help_text="When the check last executed.")
    last_status = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in CheckRunStatus],
        blank=True,
        help_text="Outcome of the newest run, denormalized so health rollups stay a single read.",
    )

    fingerprint = models.CharField(
        max_length=64,
        help_text="sha256 of the canonical subject + type + column + config. The idempotency key for authoring.",
    )

    created_source = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in CreatedSource],
        default=CreatedSource.USER,
        help_text="Whether a human or an agent authored this check.",
    )
    ai_model = models.CharField(max_length=128, blank=True, help_text="Model that generated the check, if AI-authored.")
    confidence = models.FloatField(null=True, blank=True, help_text="AI author's confidence in the check, 0-1.")
    reasoning = models.TextField(blank=True, help_text="AI author's reasoning, surfaced as review context.")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "subject_type", "subject_uuid", "fingerprint"],
                name="unique_quality_check_fingerprint",
            ),
            # Partial: a blank name is the "address me by id" case, and many checks share it.
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=~models.Q(name=""),
                name="unique_quality_check_name_per_team",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "subject_type", "subject_uuid"]),
            models.Index(
                fields=["next_run_at"],
                condition=models.Q(enabled=True) & models.Q(deleted=False),
                name="quality_check_due_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.name or f"{self.check_type} on {self.subject_name}"
