from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, TypeVar, Union, cast

from django.core.cache import cache
from django.utils.timezone import now
from rest_framework.request import Request
from rest_framework.viewsets import GenericViewSet

from posthog.models import SessionRecordingEvent, User
from posthog.models.dashboard_item import DashboardItem
from posthog.models.filters.utils import get_filter
from posthog.settings import SESSION_RECORDING_TTL, TEMP_CACHE_RESULTS_TTL
from posthog.utils import should_refresh

from .queries.sessions.session_recording import SessionRecording
from .utils import generate_cache_key, get_safe_cache


class CacheType(str, Enum):
    TRENDS = "Trends"
    FUNNEL = "Funnel"
    RETENTION = "Retention"
    SESSION = "Session"
    STICKINESS = "Stickiness"
    PATHS = "Path"


ResultPackage = Union[Dict[str, Any], List[Dict[str, Any]]]

T = TypeVar("T", bound=ResultPackage)
U = TypeVar("U", bound=GenericViewSet)


def cached_function(f: Callable[[U, Request], T]) -> Callable[[U, Request], T]:
    @wraps(f)
    def wrapper(self, request) -> T:
        # prepare caching params
        team = cast(User, request.user).team
        if not team:
            return f(self, request)

        filter = get_filter(request=request, team=team)
        cache_key = generate_cache_key("{}_{}".format(filter.toJSON(), team.pk))

        # return cached result if possible
        if not should_refresh(request):
            cached_result_package = get_safe_cache(cache_key)
            if cached_result_package and cached_result_package.get("result"):
                cached_result_package["is_cached"] = True
                return cached_result_package

        # call function being wrapped
        fresh_result_package = cast(T, f(self, request))
        # cache new data
        if isinstance(fresh_result_package, dict):
            result = fresh_result_package.get("result")
            if not isinstance(result, dict) or not result.get("loading"):
                fresh_result_package["last_refresh"] = now()
                fresh_result_package["is_cached"] = False
                cache.set(
                    cache_key, fresh_result_package, TEMP_CACHE_RESULTS_TTL,
                )
                if filter:
                    dashboard_items = DashboardItem.objects.filter(team_id=team.pk, filters_hash=cache_key)
                    dashboard_items.update(last_refresh=now())
        return fresh_result_package

    return wrapper


def cached_recording(
    f: Callable[[SessionRecording], List[SessionRecordingEvent]]
) -> Callable[[SessionRecording], List[SessionRecordingEvent]]:
    @wraps(f)
    def wrapper(self) -> List[SessionRecordingEvent]:
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
