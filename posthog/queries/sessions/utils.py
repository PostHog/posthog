from functools import wraps
from typing import Any, Callable, List, Union, cast

from django.core.cache import cache
from django.db.models import QuerySet

from posthog.models import SessionRecordingEvent
from posthog.settings import SESSION_RECORDING_TTL
from posthog.utils import generate_cache_key, get_safe_cache


def cached_recording(
    f: Callable[[Any], Union[QuerySet[Any], List[SessionRecordingEvent]]]
) -> Callable[[Any], Union[QuerySet[Any], List[SessionRecordingEvent]]]:
    @wraps(f)
    def wrapper(self) -> Union[QuerySet[Any], List[SessionRecordingEvent]]:
        # Pull from cache if it exists
        cache_key = generate_cache_key("{}_{}".format(self._team.pk, self._session_recording_id))
        cached_events = get_safe_cache(cache_key)

        if cached_events:
            return cached_events

        # Call function being wrapper
        fresh_events = cast(List[SessionRecordingEvent], f(self))
        # Cache new data
        cache.set(cache_key, fresh_events, SESSION_RECORDING_TTL)
        return fresh_events

    return wrapper
