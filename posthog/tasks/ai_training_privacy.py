from celery import shared_task

from posthog.ai_training_privacy import AITrainingPrivacyStore
from posthog.models.ai_training import privacy_enabled
from posthog.tasks.utils import CeleryQueue


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value, soft_time_limit=270, time_limit=300)
def process_ai_training_privacy_requests() -> None:
    if privacy_enabled():
        AITrainingPrivacyStore.from_settings().drain()
