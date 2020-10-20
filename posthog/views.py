from typing import Dict, Union

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from rest_framework.exceptions import AuthenticationFailed

from posthog.utils import (
    get_redis_info,
    get_redis_queue_depth,
    get_table_approx_count,
    get_table_size,
    is_postgres_alive,
    is_redis_alive,
)

from .utils import get_redis_heartbeat


def health(request):
    return HttpResponse("ok", content_type="text/plain")


def stats(request):
    stats_response: Dict[str, Union[int, str]] = {}
    stats_response["worker_heartbeat"] = get_redis_heartbeat()
    return JsonResponse(stats_response)


@never_cache
@login_required
def system_status(request):
    is_multitenancy: bool = getattr(settings, "MULTI_TENANCY", False)

    if is_multitenancy and not request.user.is_staff:
        raise AuthenticationFailed(detail="You're not authorized.")

    from .models import Element, Event

    redis_alive = is_redis_alive()
    postgres_alive = is_postgres_alive()

    metrics = list()

    metrics.append({"metric": "Redis alive", "value": redis_alive})
    metrics.append({"metric": "Postgres DB alive", "value": postgres_alive})

    if postgres_alive:
        postgres_version = connection.cursor().connection.server_version
        metrics.append(
            {
                "metric": "Postgres server version",
                "value": "{}.{}.{}".format(
                    int(postgres_version / 100 / 100), int(postgres_version / 100) % 100, postgres_version % 100
                ),
            }
        )
        event_table_count = get_table_approx_count(Event._meta.db_table)[0]["approx_count"]
        event_table_size = get_table_size(Event._meta.db_table)[0]["size"]

        element_table_count = get_table_approx_count(Element._meta.db_table)[0]["approx_count"]
        element_table_size = get_table_size(Element._meta.db_table)[0]["size"]

        metrics.append(
            {"metric": "Postgres Element table", "value": f"ca {element_table_count} rows ({element_table_size})"}
        )
        metrics.append({"metric": "Postgres Event table", "value": f"ca {event_table_count} rows ({event_table_size})"})

    if redis_alive:
        import redis

        try:
            redis_info = get_redis_info()
            redis_queue_depth = get_redis_queue_depth()
            metrics.append({"metric": "Redis version", "value": f"{redis_info['redis_version']}"})
            metrics.append({"metric": "Redis current queue depth", "value": f"{redis_queue_depth}"})
            metrics.append({"metric": "Redis connected client count", "value": f"{redis_info['connected_clients']}"})
            metrics.append({"metric": "Redis memory used", "value": f"{redis_info['used_memory_human']}"})
            metrics.append({"metric": "Redis memory peak", "value": f"{redis_info['used_memory_peak_human']}"})
            metrics.append(
                {"metric": "Redis total memory available", "value": f"{redis_info['total_system_memory_human']}"}
            )
        except redis.exceptions.ConnectionError as e:
            metrics.append(
                {"metric": "Redis metrics", "value": f"Redis connected but then failed to return metrics: {e}"}
            )

    return JsonResponse({"results": metrics})


@never_cache
def preflight_check(request):
    return JsonResponse({"django": True, "redis": is_redis_alive(), "db": is_postgres_alive()})
