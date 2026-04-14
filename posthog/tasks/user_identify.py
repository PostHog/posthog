import logging
import posthoganalytics
from celery import shared_task

from posthog.models import User

logger = logging.getLogger(__name__)


@shared_task(ignore_result=True)
def identify_task(user_id: int) -> None:
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning("identify_task: user %s no longer exists, skipping", user_id)
        return

    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="update user properties",
        properties={"$set": user.get_analytics_metadata()},
    )