from datetime import timedelta

from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from posthog.models.user import User
from posthog.models.user_analytics_deletion import UserAnalyticsDeletion


@receiver(post_delete, sender=User)
def queue_user_analytics_deletion(sender: type[User], instance: User, using: str, **kwargs: object) -> None:
    if not settings.CLOUD_DEPLOYMENT or not instance.distinct_id:
        return

    # The signal runs inside the deletion transaction, so a rollback also cancels this request.
    UserAnalyticsDeletion.objects.using(using).get_or_create(
        distinct_id=instance.distinct_id,
        # Allow in-flight captures, including the account deletion event, to reach ingestion first.
        defaults={"next_attempt_at": timezone.now() + timedelta(hours=1)},
    )
