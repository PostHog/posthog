from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from ..facade.enums import SubjectRelation, SubjectType


class DataQualityCheckRunSubject(TeamScopedRootMixin, UUIDModel):
    """One subject a run touched, as its own row: its declared subject and each one it read besides it.

    Authorizing a page of history asks which subjects the team's runs have touched and which runs
    touched a given one. Answered over ``DataQualityCheckRun`` those are aggregations over columns no
    index can serve, run before the check-runs window and before suite pagination. These rows index
    them: ``relation`` separates the run's own declared subject from the referenced ones, and the
    composite index lists either universe without scanning history.

    A ``declared`` row carries ``subject_name`` so a subject that no longer resolves can still be
    judged by the name it ran under; a ``referenced`` row stays identity-only, since names cannot
    carry that decision. ``DataQualityCheckRun.referenced_subjects`` stays authoritative for the
    referenced side: only it separates "read nothing beyond its subject" from "recorded before runs
    pinned this".
    """

    # db_index=False on both FKs: the composite index leads with team, and the unique constraint
    # leads with run, so each column is already a btree prefix. The default standalone FK index
    # would only be a redundant second copy to maintain.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False)
    run = models.ForeignKey(
        "data_quality.DataQualityCheckRun",
        on_delete=models.CASCADE,
        related_name="referenced_subject_rows",
        db_constraint=False,
        db_index=False,
    )

    relation = models.CharField(max_length=16, choices=[(r.value, r.value) for r in SubjectRelation])
    subject_type = models.CharField(max_length=32, choices=[(t.value, t.value) for t in SubjectType])
    subject_uuid = models.UUIDField()
    subject_name = models.CharField(max_length=400, blank=True)

    class Meta:
        indexes = [models.Index(fields=["team", "relation", "subject_type", "subject_uuid", "subject_name"])]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "relation", "subject_type", "subject_uuid"], name="unique_run_subject"
            )
        ]

    def __str__(self) -> str:
        return f"{self.relation} {self.subject_type} {self.subject_uuid} on run {self.run_id}"
