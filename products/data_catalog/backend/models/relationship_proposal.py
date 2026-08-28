from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from ..facade.enums import RelationshipStatus


class RelationshipProposal(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """A reviewed join fact between two warehouse tables.

    Table identity is name-based, mirroring ``DataWarehouseJoin`` itself; keys are HogQL expressions
    (casts included) so accept is a 1:1 field copy into a real join. Rejection is undirected and
    persists forever, so discovery never re-proposes the pair in either orientation -- enforced by a
    unique ``undirected_fingerprint``.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )

    source_table_name = models.CharField(max_length=400, help_text="Name of the table the join starts from.")
    source_table_key = models.CharField(max_length=400, help_text="HogQL key expression on the source table.")
    joining_table_name = models.CharField(max_length=400, help_text="Name of the table being joined in.")
    joining_table_key = models.CharField(max_length=400, help_text="HogQL key expression on the joining table.")
    field_name = models.CharField(max_length=400, help_text="Accessor the join adds to the source table.")
    configuration = models.JSONField(
        default=dict, blank=True, help_text="Extra join configuration (e.g. field mapping)."
    )

    confidence = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="Discovery confidence in this join, 0-1.",
    )
    reasoning = models.TextField(blank=True, help_text="Why this join is proposed.")
    evidence = models.JSONField(default=dict, blank=True, help_text="Sampling evidence: match rates, sample values.")

    status = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in RelationshipStatus],
        default=RelationshipStatus.PROPOSED,
        help_text="proposed, accepted (promoted to a real join), or rejected (never re-proposed).",
    )
    reviewed_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, help_text="Why the proposal was rejected.")

    created_join = models.ForeignKey(
        "data_tools.DataWarehouseJoin",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
        help_text="The join created when this proposal was accepted (promotion provenance).",
    )

    undirected_fingerprint = models.CharField(
        max_length=64,
        help_text="sha256 of the sorted {(table, key), (table, key)} pair set -- one proposal per physical join pair.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "undirected_fingerprint"], name="unique_relationship_fingerprint"),
        ]
        indexes = [models.Index(fields=["team", "status"])]

    def __str__(self) -> str:
        return f"{self.source_table_name} -> {self.joining_table_name}"
