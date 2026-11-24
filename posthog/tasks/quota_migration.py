import random
from time import time

from django.conf import settings

from celery import shared_task
from celery.signals import worker_process_init

from posthog.quota_migration import QUOTA_MIGRATION_ENABLED, QUOTA_MIGRATION_STARTED, compare_quota_stores

# Keep the parent's baseline when Celery replaces a child before the first comparison succeeds.
_migration_started_at = time()


@worker_process_init.connect
def initialize_quota_migration_metrics(**kwargs: object) -> None:
    enabled = bool(settings.QUOTA_LIMITING_REDIS_URL)
    QUOTA_MIGRATION_ENABLED.set(enabled)
    QUOTA_MIGRATION_STARTED.set(_migration_started_at if enabled else 0)


@shared_task(ignore_result=True)
def schedule_quota_redis_comparison() -> None:
    if settings.QUOTA_LIMITING_REDIS_URL:
        compare_quota_redis.apply_async(countdown=random.randint(0, 300), expires=600)


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=90)
def compare_quota_redis() -> None:
    from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource

    compare_quota_stores(
        [f"{cache.value}{resource.value}" for cache in QuotaLimitingCaches for resource in QuotaResource]
    )
