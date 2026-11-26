from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class CohortSelectionSubmission(TeamScopedRootMixin, models.Model):
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    actor = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    request_id = models.UUIDField()
    fingerprint = models.CharField(max_length=64)
    cohort = models.ForeignKey("cohorts.Cohort", null=True, on_delete=models.SET_NULL, db_constraint=False)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "actor", "request_id"], name="cohort_selection_request_unique")
        ]
