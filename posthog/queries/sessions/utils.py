from datetime import datetime
from functools import wraps
from typing import Any, Callable, List, Optional, Tuple, cast

from django.core.cache import cache

from posthog.settings import SESSION_RECORDING_TTL
from posthog.utils import generate_cache_key, get_safe_cache

DistinctId = str
Snapshots = List[Any]


def cached_recording(
    f: Callable[[Any], Tuple[Optional[DistinctId], Optional[datetime], Snapshots]]
) -> Callable[[Any], Tuple[Optional[DistinctId], Optional[datetime], Snapshots]]:
    @wraps(f)
    def wrapper(self) -> Tuple[Optional[DistinctId], Optional[datetime], Snapshots]:
        # Pull from cache if it exists
        cache_key = generate_cache_key("{}_{}".format(self._team.pk, self._session_recording_id))
        cached_data = get_safe_cache(cache_key)

        if cached_data:
            return cached_data

        # Call function being wrapper
        fresh_data = cast(Tuple[Optional[DistinctId], Optional[datetime], Snapshots], f(self))
        # Cache new data
        cache.set(cache_key, fresh_data, SESSION_RECORDING_TTL)
        return fresh_data

    return wrapper
