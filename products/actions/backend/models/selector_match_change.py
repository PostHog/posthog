from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class ActionSelectorMatchChange(TeamScopedRootMixin):
    """Classified by counting real `$autocapture` traffic under both compilers, so it cannot be
    derived from the selector text or recomputed while serving a request.
    `manage.py import_selector_match_changes` writes these rows; the action API reads them.
    """

    # Targets a hot table, so the FK carries no database constraint: creating one
    # locks posthog_team against every write while it is taken. Django still
    # cascades, because it collects related rows itself when deleting a team.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    action = models.ForeignKey(
        "actions.Action",
        on_delete=models.CASCADE,
        related_name="selector_match_changes",
    )
    step_index = models.IntegerField()
    # The selector as measured. A step edited afterwards is a different selector,
    # and the counts below no longer describe it.
    selector = models.TextField()
    old_match_count = models.BigIntegerField()
    new_match_count = models.BigIntegerField()
    measured_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["action", "step_index"], name="unique_selector_match_change_per_step")
        ]

    def __str__(self) -> str:
        return f"action {self.action_id} step {self.step_index}"
