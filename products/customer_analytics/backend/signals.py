from typing import Any

from django.db import transaction

from posthog.exceptions_capture import capture_exception
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.tagged_item import TaggedItem
from posthog.models.user import User

from products.customer_analytics.backend.events import capture_account_tag_added


@mutable_receiver(model_activity_signal, sender=TaggedItem)
def emit_account_tag_added(
    sender: type[TaggedItem],
    activity: str,
    after_update: TaggedItem | None,
    user: User | None = None,
    **kwargs: Any,
) -> None:
    """Emit $account_tag_added post-commit when a tag lands on an account.

    Every add path creates the TaggedItem via get_or_create, which no-ops (and
    fires no signal) when the tag is already present — so a workflow adding its
    own trigger tag cannot loop.
    """
    if activity != "created" or after_update is None or after_update.account_id is None:
        return

    def emit() -> None:
        try:
            capture_account_tag_added(after_update, user)
        except Exception as e:
            capture_exception(e)

    transaction.on_commit(emit)
