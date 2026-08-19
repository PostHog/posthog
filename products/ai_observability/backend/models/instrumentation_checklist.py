from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class AIObservabilityChecklistItemState(TeamScopedRootMixin, UUIDModel):
    """A team's recorded intent for one instrumentation check.

    Only checks somebody has acted on get a row. Computed status is never stored:
    it is derived from a query on every read.
    """

    class Status(models.TextChoices):
        DISMISSED = "dismissed", "Dismissed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    check_key = models.CharField(max_length=64)
    # Null means project-wide. Reserved for per-workload checklists.
    scope = models.CharField(max_length=200, null=True, blank=True)
    status = models.CharField(max_length=32, choices=Status)
    updated_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "llm_analytics_checklistitemstate"
        constraints = [
            models.UniqueConstraint(fields=["team", "scope", "check_key"], name="uniq_llma_checklist_item_state"),
            # SQL treats NULLs as distinct, so the constraint above lets duplicates through
            # whenever scope IS NULL, which is the project-wide case and the only one in use.
            models.UniqueConstraint(
                fields=["team", "check_key"],
                condition=models.Q(scope__isnull=True),
                name="uniq_llma_checklist_item_state_global",
            ),
        ]
