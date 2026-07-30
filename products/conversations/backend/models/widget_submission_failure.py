from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class WidgetSubmissionFailure(TeamScopedRootMixin, UUIDModel):
    """A widget message the server rejected, retained so the submitter can be followed up with.

    Only written when the request carried something that identifies the submitter, since a
    rejection with no session and no distinct_id leaves nobody to reach.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False)
    distinct_id = models.CharField(max_length=400, null=True, blank=True)
    widget_session_id = models.CharField(max_length=64, null=True, blank=True)
    ticket_id = models.UUIDField(null=True, blank=True)
    error_fields = models.JSONField(default=list, blank=True)
    identity_attempted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_conversations_widget_submission_failure"
        indexes = [
            models.Index(fields=["team", "created_at"], name="posthog_cwsf_team_created_idx"),
            models.Index(fields=["created_at"], name="posthog_cwsf_created_idx"),
        ]

    def __str__(self) -> str:
        return f"WidgetSubmissionFailure {self.id} ({', '.join(self.error_fields)})"
