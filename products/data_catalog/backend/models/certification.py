from django.db import models

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from ..facade.enums import CertificationStatus


class TableCertification(CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """A human-vouched trust mark on a warehouse table or view.

    Exactly one target (table XOR saved_query). Revocation is a hard delete (activity-logged in the
    logic layer), so there is no soft-delete here; when the target itself soft-deletes, the loader and
    API reads exclude the row rather than cascading.
    """

    objects = TeamScopedManager()

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )
    table = models.ForeignKey(
        "warehouse_sources.DataWarehouseTable",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
        help_text="The warehouse table this mark applies to (XOR saved_query).",
    )
    saved_query = models.ForeignKey(
        "data_modeling.DataWarehouseSavedQuery",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
        help_text="The warehouse view this mark applies to (XOR table).",
    )

    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in CertificationStatus],
        default=CertificationStatus.PROPOSED,
        help_text="proposed, certified (prefer this source), or deprecated (avoid this source).",
    )
    notes = models.TextField(
        blank=True, help_text="Why this mark exists, e.g. 'canonical MRR source, refreshed daily'."
    )
    certified_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    certified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(table__isnull=False, saved_query__isnull=True)
                    | models.Q(table__isnull=True, saved_query__isnull=False)
                ),
                name="certification_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=["team", "table"],
                condition=models.Q(table__isnull=False),
                name="unique_certification_per_table",
            ),
            models.UniqueConstraint(
                fields=["team", "saved_query"],
                condition=models.Q(saved_query__isnull=False),
                name="unique_certification_per_saved_query",
            ),
        ]
        indexes = [models.Index(fields=["team", "status"])]

    def __str__(self) -> str:
        return f"{self.status} certification"
