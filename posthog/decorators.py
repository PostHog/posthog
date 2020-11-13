from enum import Enum
from functools import wraps
from typing import Callable, cast

from django.core.cache import cache
from django.http.request import HttpRequest

from posthog.models import Filter, Team, User
from posthog.utils import generate_cache_key

from .utils import generate_cache_key


class CacheType(str, Enum):
    TRENDS = "Trends"
    FUNNEL = "Funnel"


def cached_function(cache_type: CacheType, expiry_seconds: int = 30):
    def parameterized_decorator(f: Callable):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # prepare caching params
            request: HttpRequest = args[1]
            team: Team = cast(User, request.user).team
            if cache_type == CacheType.TRENDS:
                filter = Filter(request=request)
                cache_key = generate_cache_key(filter.toJSON() + "_" + str(team.pk))
                payload = {"filter": filter.toJSON(), "team_id": team.pk}
            elif cache_type == CacheType.FUNNEL:
                pk = args[2]
                cache_key = generate_cache_key("funnel_{}_{}".format(pk, team.pk))
                payload = {"funnel_id": pk, "team_id": team.pk}
            else:
                raise ValueError("Invalid cache type!")
            # return cached result if possible
            if not request.GET.get("refresh", False):
                cached_result = cache.get(cache_key)
                if cached_result:
                    return cached_result["result"]
            # call function being wrapped
            result = f(*args, **kwargs)
            # cache new data
            if result is not None:
                cache.set(
                    cache_key, {"result": result, "details": payload, "type": cache_type,}, expiry_seconds,
                )
            return result

        return wrapper

    return parameterized_decorator
