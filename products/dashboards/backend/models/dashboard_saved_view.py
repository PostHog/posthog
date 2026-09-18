from typing import TYPE_CHECKING, Any

from django.db import models
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    from posthog.models.user import User


class DashboardSavedView(TeamScopedRootMixin, UUIDModel):
    class Scope(models.TextChoices):
        PRIVATE = "private", "Private"
        TEAM = "team", "Team"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    name = models.CharField(max_length=200)
    filters = models.JSONField(default=dict)
    scope = models.CharField(max_length=20, choices=Scope, default=Scope.PRIVATE, db_default=Scope.PRIVATE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    all_teams = models.Manager()

    def can_modify(self, user: "User") -> bool:
        return self.scope != self.Scope.PRIVATE or self.created_by_id == user.id

    def can_change_scope(self, user: "User") -> bool:
        return self.scope != self.Scope.TEAM or self.created_by_id == user.id

    class Meta(TeamScopedRootMixin.Meta):
        db_table = "posthog_dashboard_saved_view"
        ordering = ["id"]
        indexes = [
            models.Index(
                fields=["team", "id"],
                condition=models.Q(scope="team"),
                name="dash_saved_view_team_idx",
            ),
            models.Index(
                fields=["team", "created_by", "id"],
                condition=models.Q(scope="private"),
                name="dash_saved_view_private_idx",
            ),
        ]


@receiver(pre_delete, sender="posthog.User")
def delete_private_views_for_deleted_user(sender: type[models.Model], instance: models.Model, **kwargs: Any) -> None:
    DashboardSavedView.all_teams.filter(scope=DashboardSavedView.Scope.PRIVATE, created_by_id=instance.pk).delete()
