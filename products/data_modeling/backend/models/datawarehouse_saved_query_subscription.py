from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UpdatedMetaFields, UUIDTModel, sane_repr


class DataWarehouseSavedQuerySubscription(TeamScopedRootMixin, UpdatedMetaFields, UUIDTModel):
    """One user's choice to watch, or stop watching, a saved query (view) for failure notifications.

    The view's creator watches it without a row. A row with `subscribed=False` is how the creator
    opts out; for any other user a `subscribed=False` row is the same as no row.
    """

    # db_constraint=False on the FKs to hot tables (posthog_team, posthog_user): creating a real FK
    # constraint takes a SHARE ROW EXCLUSIVE lock on the parent, which stalls under write traffic. Team
    # scoping is enforced at the app level by TeamScopedRootMixin. The saved_query FK targets a non-hot
    # table, so it keeps its constraint.
    # The team and saved_query FKs skip their own index because the (team, user) index and the
    # (saved_query, user) unique constraint already lead with those columns.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    saved_query = models.ForeignKey(
        "data_modeling.DataWarehouseSavedQuery", on_delete=models.CASCADE, db_index=False, related_name="subscriptions"
    )
    subscribed = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    __repr__ = sane_repr("saved_query_id", "user_id", "subscribed")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["saved_query", "user"], name="unique_saved_query_subscription_user"),
        ]
        indexes = [
            models.Index(fields=["team", "user"], name="dm_sq_subscription_team_user"),
        ]
