import uuid
from typing import Any, cast

from django.core.validators import RegexValidator
from django.db import models
from django.db.models.deletion import Collector

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDModel

from ..facade.enums import CheckRunStatus, CheckSeverity, CreatedSource, SubjectStatus, SubjectType

# A check name is an addressable handle in `information_schema.data_quality_checks` and in agent
# prose, so it follows the same bare-identifier discipline as a metric name.
CHECK_NAME_REGEX = r"^[A-Za-z][A-Za-z0-9_]*$"

SUBJECT_STATUS_FIELD = "subject_status"

# `deleted` is nullable, so "not deleted" has to name the null case too.
ACTIVE = models.Q(deleted=False) | models.Q(deleted__isnull=True)

validate_check_name = RegexValidator(
    regex=CHECK_NAME_REGEX,
    message="Name must start with a letter and contain only letters, numbers, and underscores.",
)


def orphan_check_on_subject_delete(collector: Collector, field: models.ForeignKey, sub_objs: Any, using: str) -> None:
    """Unbind the check and mark it orphaned in the same delete, instead of a plain ``SET_NULL``.

    Nulling the key alone leaves the row reading ``active`` with no subject, and nothing would ever
    correct it: checks run when their subject's data changes, and a deleted subject never changes
    again.

    The status update is queued first on purpose. The collector runs its field updates in insertion
    order against the same queryset, which filters on the key this handler is about to null -- queued
    second, it would match no rows.

    ``sub_objs`` is the lazy queryset ``lazy_sub_objs`` asks for, which django-stubs types as an
    indexable collection.
    """
    status_field = cast(models.Field, field.model._meta.get_field(SUBJECT_STATUS_FIELD))
    collector.add_field_update(status_field, SubjectStatus.ORPHANED.value, sub_objs)
    collector.add_field_update(field, None, sub_objs)


orphan_check_on_subject_delete.lazy_sub_objs = True  # type: ignore[attr-defined]


class DataQualityCheck(
    ModelActivityMixin, TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, DeletedMetaFields, UUIDModel
):
    """An assertion about a warehouse table or view, in the ``dbt test`` sense.

    A check passes when its compiled query finds zero failing rows. The definition is the source of
    truth here; ``fingerprint`` makes agent authoring idempotent (re-creating a semantically
    identical *active* check upserts instead of duplicating), and it is also the stable identity a
    git-synced config file would round-trip against. Editing the assertion recomputes it in place:
    the check keeps its id, history, and latest status.

    The subject is one of two foreign keys -- ``saved_query`` (views and matviews) or ``table``
    (warehouse source tables) -- and never both. The data modeling Node for a subject is resolved at
    trigger time rather than referenced here: node rows are per-DAG structural records that DAG sync
    deletes and recreates, so they cannot anchor a check's identity, and a table in no DAG has no
    node at all. A hard-deleted subject nulls its FK (the check turns ``orphaned`` and is skipped);
    orphaned checks fall outside the partial fingerprint constraints, so duplicate-fingerprint
    orphans are possible and harmless.

    ``last_status`` / ``last_run_at`` are denormalized from the newest ``DataQualityCheckRun`` so
    per-subject health is a single indexed read rather than a correlated subquery over run history.

    Checks carry no cadence: they run when their subject's data changes (a sync completes, a
    materialization runs) or on demand, never on a timer of their own.
    """

    # db_constraint=False on FKs to hot tables (posthog_team, posthog_user): a real FK constraint
    # takes SHARE ROW EXCLUSIVE on the parent, stalling writes under traffic. Scoping/integrity is
    # enforced at the app layer.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    definition_author = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
        help_text="Who last changed what this check asserts. Automated runs authorize as them, "
        "falling back to created_by.",
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
        help_text="Kind of catalog object being checked: table or view. Kept so orphaned checks stay readable.",
    )
    saved_query = models.ForeignKey(
        "data_modeling.DataWarehouseSavedQuery",
        on_delete=orphan_check_on_subject_delete,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
        help_text="The view or matview this check audits. Exclusive with table.",
    )
    table = models.ForeignKey(
        "warehouse_sources.DataWarehouseTable",
        on_delete=orphan_check_on_subject_delete,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
        help_text="The warehouse source table this check audits. Exclusive with saved_query.",
    )
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

    # No choices: the check registry is the source of truth for which types exist, and Django
    # serializes choices into migration state -- adding a type would then need a migration.
    check_type = models.CharField(
        max_length=32,
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

    last_run_at = models.DateTimeField(null=True, blank=True, help_text="When the check last executed.")
    last_status = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in CheckRunStatus],
        blank=True,
        help_text="Outcome of the newest run, denormalized so health rollups stay a single read.",
    )
    # Denormalized for the same reason as last_status: "failing since when" is the first question a
    # failing check raises, and the answer can be older than any page of run history.
    last_succeeded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the check last passed. Null means it has not passed within the run retention window.",
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
            # The subject invariant: at most one FK set, and subject_type must match the FK that is.
            # Both FKs null is the orphaned state.
            models.CheckConstraint(
                name="quality_check_subject_binding",
                condition=(
                    ~models.Q(saved_query__isnull=False, table__isnull=False)
                    & ~models.Q(saved_query__isnull=False, subject_type=SubjectType.TABLE)
                    & ~models.Q(table__isnull=False, subject_type=SubjectType.VIEW)
                ),
            ),
            # Partial per FK: orphaned checks (both FKs null) are exempt on purpose, and so are
            # soft-deleted ones -- a deleted definition may be authored again, as a new check with
            # its own id and history, rather than resurrecting the row that was deleted.
            models.UniqueConstraint(
                fields=["team", "saved_query", "fingerprint"],
                condition=models.Q(saved_query__isnull=False) & ACTIVE,
                name="unique_quality_check_fp_view",
            ),
            models.UniqueConstraint(
                fields=["team", "table", "fingerprint"],
                condition=models.Q(table__isnull=False) & ACTIVE,
                name="unique_quality_check_fp_table",
            ),
            # Partial on both counts: a blank name is the "address me by id" case, which many checks
            # share, and a deleted check keeps its name only as history -- holding the name against a
            # new check would make a delete irreversible for anyone who wants that name back.
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=~models.Q(name="") & ACTIVE,
                name="unique_quality_check_name_per_team",
            ),
        ]
        indexes = [
            models.Index(
                fields=["team", "saved_query"],
                condition=models.Q(saved_query__isnull=False),
                name="quality_check_saved_query_idx",
            ),
            models.Index(
                fields=["team", "table"],
                condition=models.Q(table__isnull=False),
                name="quality_check_table_idx",
            ),
        ]

    @property
    def subject_uuid(self) -> "uuid.UUID | None":
        """Id of whichever subject FK is set; None once orphaned."""
        return self.saved_query_id or self.table_id

    def __str__(self) -> str:
        return self.name or f"{self.check_type} on {self.subject_name}"
