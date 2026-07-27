from django.db.models.signals import post_delete
from django.dispatch import receiver

from posthog.models.user import User
from posthog.session.models import Session


@receiver(post_delete, sender=User)
def delete_sessions_on_user_deletion(sender: type[User], instance: User, **kwargs: object) -> None:
    """Purge a deleted user's login session rows.

    `Session.user_id` is a plain BigIntegerField (no FK), so there is no cascade — without this the
    deleted user's ip / location / user-agent would linger on the row until the session expires.
    """
    Session.objects.filter(user_id=instance.pk).delete()
