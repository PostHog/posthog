from celery import shared_task

from posthog.tasks.utils import CeleryQueue

from products.ai_training.backend.facade.api import privacy_enabled
from products.ai_training.backend.privacy.store import AITrainingPrivacyStore


@shared_task(
    name="posthog.tasks.ai_training_privacy.process_ai_training_privacy_requests",
    ignore_result=True,
    queue=CeleryQueue.AI_RESEARCH_PRIVACY.value,
    soft_time_limit=270,
    time_limit=300,
)
def process_ai_training_privacy_requests() -> None:
    if privacy_enabled():
        AITrainingPrivacyStore.from_settings().drain()
