from typing import TYPE_CHECKING, Any

from posthog.models.activity_logging.activity_log import ActivityScope, Detail, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.customer_analytics.backend.models.account_view import AccountView

if TYPE_CHECKING:
    from posthog.models import User


@mutable_receiver(model_activity_signal, sender=AccountView)
def handle_account_view_change(
    sender: type[AccountView],
    scope: ActivityScope,
    before_update: AccountView | None,
    after_update: AccountView | None,
    activity: str,
    user: "User | None",
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    instance = after_update or before_update
    if instance is None:
        return
    changes = changes_between(scope, previous=before_update, current=after_update)
    resolved_activity = activity
    deleted_change = next((change for change in changes if change.field == "deleted_at"), None)
    if deleted_change and deleted_change.after:
        resolved_activity = "deleted"

    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=instance.id,
        scope=scope,
        activity=resolved_activity,
        detail=Detail(changes=changes, name=instance.name),
    )
