from posthog.ingress.dispatch.dedup import INGRESS_DEDUP_CACHE_ALIAS

LOCMEM = {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}

# Both aliases share one LocMemCache store, as the test settings do, so clearing one clears both.
LOCMEM_CACHES = {"default": LOCMEM, INGRESS_DEDUP_CACHE_ALIAS: LOCMEM}
