from typing import Dict, Union

from django.db import DatabaseError
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache

from .models.user import User
from .utils import get_redis_heartbeat


def health(request):
    return HttpResponse("ok", content_type="text/plain")


def stats(request):
    stats_response: Dict[str, Union[int, str]] = {}
    stats_response["worker_heartbeat"] = get_redis_heartbeat()
    return JsonResponse(stats_response)


@never_cache
def preflight_check(request):
    redis: bool = False
    db: bool = False
    try:
        redis = get_redis_heartbeat() != "offline"
    except BaseException:
        pass

    try:
        User.objects.count()
        db = True
    except DatabaseError:
        pass

    return JsonResponse({"django": True, "redis": redis, "db": db})
