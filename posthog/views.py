from typing import Dict, Union
from django.http import HttpResponse
from django.conf import settings
import json
import redis
import time

if settings.REDIS_URL:
    redis_instance = redis.from_url(settings.REDIS_URL, db=0)
else:
    redis_instance = None


def health(request):
    return HttpResponse("ok", content_type="text/plain")


def stats(request):
    stats_response: Dict[str, Union[int, str]] = {}

    last_heartbeat = redis_instance.get("POSTHOG_HEARTBEAT") if redis_instance else None
    worker_heartbeat = int(time.time()) - int(last_heartbeat) if last_heartbeat else None

    if worker_heartbeat and worker_heartbeat < 300:
        stats_response['worker_heartbeat'] = worker_heartbeat
    else:
        stats_response['worker_heartbeat'] = 'offline'

    return HttpResponse(json.dumps(stats_response), content_type="application/json")
