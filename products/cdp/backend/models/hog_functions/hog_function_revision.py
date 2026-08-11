from typing import Any

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class HogFunctionRevision(TeamScopedRootMixin, UUIDModel):
    """Append-only snapshot of a function's live config, written whenever that config changes.
    Rollback copies a snapshot back into the draft; workers never read this table."""

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["hog_function", "version"], name="unique_hogfunction_revision_version"),
        ]

    # db_constraint=False on team/created_by: a real FK constraint to a hot table (posthog_team,
    # posthog_user) takes a parent-table lock on creation; enforcement stays app-level.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    hog_function = models.ForeignKey("cdp.HogFunction", on_delete=models.CASCADE, related_name="revisions")
    version = models.IntegerField(help_text="Function version this snapshot was published as.")
    content = models.JSONField(
        help_text="Full snapshot of the function's config fields (hog, inputs_schema, inputs, filters, mappings, masking) at this version."
    )
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args: Any, **kwargs: Any) -> None:
        # Fail loudly, not with an AttributeError, when the required FK was never set.
        if not self.hog_function_id:
            raise ValueError("hog_function must be set before saving a HogFunctionRevision")
        # A revision's tenant scope always mirrors its function's. A mismatched (team, hog_function)
        # pair would leak the revision into the wrong team's history — fail-closed reads filter on
        # this row's team_id, not the function's.
        self.team_id = self.hog_function.team_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"HogFunctionRevision {self.hog_function_id} v{self.version}"
