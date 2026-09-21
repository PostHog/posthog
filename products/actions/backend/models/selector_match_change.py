from typing import TYPE_CHECKING

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin

if TYPE_CHECKING:
    from products.actions.backend.models.action import Action


class ActionSelectorMatchChange(TeamScopedRootMixin):
    """Classified by counting real `$autocapture` traffic under both compilers, so it cannot be
    derived from the selector text or recomputed while serving a request.
    `manage.py import_selector_match_changes` writes these rows; the action API reads them.
    """

    # Targets a hot table, so the FK carries no database constraint: creating one
    # locks posthog_team against every write while it is taken. Django still
    # cascades, because it collects related rows itself when deleting a team.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    action = models.ForeignKey(
        "actions.Action",
        on_delete=models.CASCADE,
        related_name="selector_match_changes",
    )
    step_index = models.IntegerField()
    selector = models.TextField()
    old_match_count = models.BigIntegerField()
    new_match_count = models.BigIntegerField()
    measured_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["action", "step_index"], name="unique_selector_match_change_per_step")
        ]

    def describes(self, action: "Action") -> bool:
        """Whether the measured selector is still the one at that step. A step edited since
        the measurement is a different selector, and these counts say nothing about it."""
        if self.step_index >= len(action.steps):
            return False
        return (action.steps[self.step_index].selector or "").strip() == self.selector

    def __str__(self) -> str:
        return f"action {self.action_id} step {self.step_index}"
