import posthoganalytics
from celery import shared_task

from posthog.models import User


@shared_task(ignore_result=True)
def identify_task(user_id: int) -> None:
    # The user can be deleted between scheduling and execution; treat as a no-op rather than crashing the worker.
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return

    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="update user properties",
        properties={"$set": user.get_analytics_metadata()},
    )
