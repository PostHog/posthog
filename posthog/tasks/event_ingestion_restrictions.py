from celery import shared_task
from redis.exceptions import RedisError

from posthog.models.event_ingestion_restriction_config import regenerate_redis_for_restriction_type
from posthog.tasks.utils import CeleryQueue


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(RedisError,),
    max_retries=5,
    retry_backoff=True,
)
def regenerate_restriction_type_in_redis(restriction_type: str) -> None:
    regenerate_redis_for_restriction_type(restriction_type)
