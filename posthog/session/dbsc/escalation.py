import hashlib

from django.core.cache import BaseCache, caches

import structlog

from posthog.session.dbsc.cookies import COOKIE_MAX_AGE_SECONDS

logger = structlog.get_logger(__name__)

# A browser that holds the key refreshes within one bound-cookie lifetime, so its refusals stop well before this.
SOFT_REFUSAL_LIMIT = 20
WINDOW_SECONDS = COOKIE_MAX_AGE_SECONDS
_HEALTHY_KEY = "dbsc_refresh_healthy"
_COUNT_PREFIX = "dbsc_soft_refusals:"


def _store() -> BaseCache:
    return caches["dbsc_challenges"]


def mark_refresh_healthy() -> None:
    try:
        _store().set(_HEALTHY_KEY, True, WINDOW_SECONDS)
    except Exception:
        logger.warning("dbsc_refresh_health_unwritable", exc_info=True)


def is_repeated(binding_id: str) -> bool:
    """Whether refusals that keep the session continue while other browsers refresh.

    Their headers come from the client, so only repetition separates a cookie copy from a browser
    that could not refresh. While no refresh succeeds anywhere, our refresh endpoint is the likely cause.
    """
    try:
        store = _store()
        if not store.get(_HEALTHY_KEY):
            return False
        key = _COUNT_PREFIX + hashlib.sha256(binding_id.encode()).hexdigest()
        store.add(key, 0, WINDOW_SECONDS)
        return store.incr(key) > SOFT_REFUSAL_LIMIT
    except Exception:
        logger.warning("dbsc_refusal_count_unavailable", exc_info=True)
        return False
