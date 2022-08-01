from django.conf import settings


def as_cache_update_lock_key(cache_key: str) -> str:
    return f"processing-for-cache-update-{cache_key}"


def clear_cache_update_lock(cache_key: str) -> None:
    from posthog.redis import get_client

    get_client().delete(as_cache_update_lock_key(cache_key))


def should_queue_for_update(cache_key: str) -> bool:
    from posthog.redis import get_client

    return bool(
        get_client().set(
            name=as_cache_update_lock_key(cache_key), value=cache_key, nx=True, ex=settings.CACHE_QUEUE_LOCK_TTL
        )
    )
