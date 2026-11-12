from django.core.cache import caches

from celery import shared_task


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=6, ignore_result=True)
def retry_ip_restrictions_invalidation(cache_keys: list[str]) -> None:
    caches["organization_access"].delete_many(cache_keys)
