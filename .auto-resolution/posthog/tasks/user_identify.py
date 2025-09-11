import posthoganalytics
from celery import shared_task

from posthog.models import User


@shared_task(ignore_result=True)
def identify_task(user_id: int) -> None:
    user = User.objects.get(id=user_id)
    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="update user properties",
        properties={"$set": user.get_analytics_metadata()},
    )
