from functools import partial

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from posthog.models.user import User


@receiver(post_delete, sender=User)
def queue_user_analytics_deletion(sender: type[User], instance: User, using: str, **kwargs: object) -> None:
    if not settings.CLOUD_DEPLOYMENT or not instance.distinct_id:
        return

    from posthog.tasks.user_analytics_deletion import delete_user_analytics  # noqa: PLC0415

    # Let in-flight captures reach ingestion before deleting their person and history.
    transaction.on_commit(
        partial(delete_user_analytics.apply_async, args=(instance.distinct_id,), countdown=3600),
        using=using,
        robust=True,
    )
