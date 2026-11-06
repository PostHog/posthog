"""
Hybrid session-cache storage to avoid race conditions when concurrent requests overwrite session data.
"""

from typing import Any, Optional

from django.contrib.sessions.backends.base import SessionBase
from django.core.cache import cache


class SessionCache:
    """
    Store temporary data in cache (keyed by session ID) to survive concurrent session saves.

    Use this when multiple concurrent requests might overwrite session changes.
    """

    CACHE_KEY_PREFIX = "session_cache"

    def __init__(self, session: SessionBase):
        self.session = session
        self.session_key = session.session_key

    def _get_cache_key(self, key: str) -> str:
        return f"{self.CACHE_KEY_PREFIX}:{self.session_key}:{key}"

    def set(
        self,
        key: str,
        value: Any,
        timeout: Optional[int] = None,
        store_in_session: bool = True,
    ) -> None:
        """Store value in cache (and optionally session)."""
        cache_key = self._get_cache_key(key)
        cache.set(cache_key, value, timeout=timeout)

        if store_in_session:
            self.session[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve value (checks cache first, then session)."""
        cache_key = self._get_cache_key(key)
        value = cache.get(cache_key)

        if value is not None:
            return value

        return self.session.get(key, default)

    def delete(self, key: str) -> None:
        cache_key = self._get_cache_key(key)
        cache.delete(cache_key)
        self.session.pop(key, None)

    def exists(self, key: str) -> bool:
        cache_key = self._get_cache_key(key)
        if cache.get(cache_key) is not None:
            return True

        return key in self.session
