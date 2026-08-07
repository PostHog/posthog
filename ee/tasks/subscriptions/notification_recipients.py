from posthog.models import User

from products.exports.backend.models.subscription import Subscription


def get_notification_creator(subscription: Subscription) -> User | None:
    """Single source of truth for who may be notified about a subscription.

    Delivery-failure and auto-disable notifications both route here so an eligibility
    change can never leave the email and in-app paths disagreeing about the recipient.
    """
    creator = subscription.created_by
    creator_id = subscription.created_by_id
    if creator is None or creator_id is None:
        return None
    if not subscription.team.all_users_with_access().filter(id=creator_id).exists():
        return None
    return creator
