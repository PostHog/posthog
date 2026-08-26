from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from ..facade.enums import SubjectType


class DataQualityCheckRunSubject(TeamScopedRootMixin, UUIDModel):
    """One subject a run read besides its own, as its own row.

    The same identities ``DataQualityCheckRun.referenced_subjects`` records, indexed. Authorizing a
    page of history asks two questions -- which subjects the team's runs have read, and which runs
    read a given one -- and both are aggregations over a JSONB column that no index can serve, run
    before the check-runs window and before suite pagination.

    The JSON column stays authoritative: only it separates "read nothing beyond its subject" from
    "recorded before runs pinned this", and the gate turns on that difference. These rows are an
    index over it, never a second source of truth.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    run = models.ForeignKey(
        "data_quality.DataQualityCheckRun",
        on_delete=models.CASCADE,
        related_name="referenced_subject_rows",
        db_constraint=False,
    )

    subject_type = models.CharField(max_length=32, choices=[(t.value, t.value) for t in SubjectType])
    subject_uuid = models.UUIDField()

    class Meta:
        indexes = [models.Index(fields=["team", "subject_type", "subject_uuid"])]
        constraints = [
            models.UniqueConstraint(fields=["run", "subject_type", "subject_uuid"], name="unique_run_subject")
        ]

    def __str__(self) -> str:
        return f"{self.subject_type} {self.subject_uuid} read by run {self.run_id}"
