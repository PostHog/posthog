from django.core.cache import cache

from posthog.models import Filter
from posthog.utils import generate_cache_key

from .utils import generate_cache_key

TRENDS_ENDPOINT = "Trends"
FUNNEL_ENDPOINT = "Funnel"


def cached_function(cache_type: str, expiry=30):
    def inner_decorator(f):
        def wrapper(*args, **kw):

            cache_key = ""

            # prepare caching params
            request = args[1]
            team = request.user.team_set.get()
            payload = None
            refresh = request.GET.get("refresh", None)

            if cache_type == TRENDS_ENDPOINT:
                filter = Filter(request=request)
                cache_key = generate_cache_key(filter.toJSON() + "_" + str(team.pk))
                payload = {"filter": filter.toJSON(), "team_id": team.pk}

            if not refresh:
                # return result if cached
                cached_result = cache.get(cache_key)
                if cached_result:
                    return cached_result["result"]

            # call wrapped function
            result = f(*args, **kw)

            # cache new data using
            if result and payload:
                cache.set(
                    cache_key, {"result": result, "details": payload, "type": cache_type,}, expiry,
                )

            return result

        return wrapper

    return inner_decorator
