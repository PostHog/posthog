from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UpdatedMetaFields, UUIDModel, sane_repr


class NodeSubscription(TeamScopedRootMixin, UpdatedMetaFields, UUIDModel):
    """One user's choice to watch, or stop watching, a DAG node for failure notifications.

    A node's default watcher watches it without a row. A row with `subscribed=False` is how that
    default watcher opts out; for any other user a `subscribed=False` row is the same as no row.
    """

    # db_constraint=False on the FKs to hot tables (posthog_team, posthog_user): creating a real FK
    # constraint takes a SHARE ROW EXCLUSIVE lock on the parent, which stalls under write traffic. Team
    # scoping is enforced at the app level by TeamScopedRootMixin. The node FK targets a non-hot
    # table, so it keeps its constraint.
    # The team and node FKs skip their own index because the (team, user) index and the
    # (node, user) unique constraint already lead with those columns.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    node = models.ForeignKey(
        "data_modeling.Node", on_delete=models.CASCADE, db_index=False, related_name="subscriptions"
    )
    subscribed = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    __repr__ = sane_repr("node_id", "user_id", "subscribed")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["node", "user"], name="unique_node_subscription_user"),
        ]
        indexes = [
            models.Index(fields=["team", "user"], name="dm_node_subscription_team_user"),
        ]
