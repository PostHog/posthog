from typing import Dict, List, Union

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DEFAULT_DB_ALIAS, connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from rest_framework.exceptions import AuthenticationFailed

from posthog.ee import is_ee_enabled
from posthog.models import User
from posthog.settings import TEST
from posthog.utils import (
    get_redis_info,
    get_redis_queue_depth,
    get_table_approx_count,
    get_table_size,
    is_celery_alive,
    is_plugin_server_alive,
    is_postgres_alive,
    is_redis_alive,
)

from .utils import get_celery_heartbeat


def health(request):
    executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    status = 503 if plan else 200
    if status == 503:
        return HttpResponse("Migrations are not up to date", status=status, content_type="text/plain")
    if status == 200:
        return HttpResponse("ok", status=status, content_type="text/plain")


def stats(request):
    stats_response: Dict[str, Union[int, str]] = {}
    stats_response["worker_heartbeat"] = get_celery_heartbeat()
    return JsonResponse(stats_response)


@never_cache
@login_required
def system_status(request):
    is_multitenancy: bool = getattr(settings, "MULTI_TENANCY", False)

    if is_multitenancy and not request.user.is_staff:
        raise AuthenticationFailed(detail="You're not authorized.")

    from .models import Element, Event, SessionRecordingEvent

    redis_alive = is_redis_alive()
    postgres_alive = is_postgres_alive()

    metrics: List[Dict[str, Union[str, bool, int, float]]] = []

    metrics.append(
        {
            "key": "analytics_database",
            "metric": "Analytics database in use",
            "value": "ClickHouse" if is_ee_enabled() else "Postgres",
        }
    )

    metrics.append({"key": "db_alive", "metric": "Postgres database alive", "value": postgres_alive})
    if postgres_alive:
        postgres_version = connection.cursor().connection.server_version
        metrics.append(
            {
                "key": "pg_version",
                "metric": "Postgres version",
                "value": f"{postgres_version // 10000}.{(postgres_version // 100) % 100}.{postgres_version % 100}",
            }
        )
        event_table_count = get_table_approx_count(Event._meta.db_table)[0]["approx_count"]
        event_table_size = get_table_size(Event._meta.db_table)[0]["size"]

        element_table_count = get_table_approx_count(Element._meta.db_table)[0]["approx_count"]
        element_table_size = get_table_size(Element._meta.db_table)[0]["size"]

        session_recording_event_table_count = get_table_approx_count(SessionRecordingEvent._meta.db_table)[0][
            "approx_count"
        ]
        session_recording_event_table_size = get_table_size(SessionRecordingEvent._meta.db_table)[0]["size"]

        metrics.append(
            {"metric": "Postgres elements table size", "value": f"~{element_table_count} rows (~{element_table_size})"}
        )
        metrics.append(
            {"metric": "Postgres events table size", "value": f"~{event_table_count} rows (~{event_table_size})"}
        )
        metrics.append(
            {
                "metric": "Postgres session recording table size",
                "value": f"~{session_recording_event_table_count} rows (~{session_recording_event_table_size})",
            }
        )

    metrics.append({"key": "redis_alive", "metric": "Redis alive", "value": redis_alive})
    if redis_alive:
        import redis

        try:
            redis_info = get_redis_info()
            redis_queue_depth = get_redis_queue_depth()
            metrics.append({"metric": "Redis version", "value": f"{redis_info.get('redis_version')}"})
            metrics.append({"metric": "Redis current queue depth", "value": f"{redis_queue_depth}"})
            metrics.append(
                {"metric": "Redis connected client count", "value": f"{redis_info.get('connected_clients')}"}
            )
            metrics.append({"metric": "Redis memory used", "value": f"{redis_info.get('used_memory_human', '?')}B"})
            metrics.append(
                {"metric": "Redis memory peak", "value": f"{redis_info.get('used_memory_peak_human', '?')}B"}
            )
            metrics.append(
                {
                    "metric": "Redis total memory available",
                    "value": f"{redis_info.get('total_system_memory_human', '?')}B",
                }
            )
        except redis.exceptions.ConnectionError as e:
            metrics.append(
                {"metric": "Redis metrics", "value": f"Redis connected but then failed to return metrics: {e}"}
            )

    return JsonResponse({"results": metrics})


@never_cache
def preflight_check(request):
    return JsonResponse(
        {
            "django": True,
            "redis": is_redis_alive() or TEST,
            "plugins": is_plugin_server_alive() or TEST,
            "celery": is_celery_alive() or TEST,
            "db": is_postgres_alive(),
            "initiated": User.objects.exists(),
            "cloud": settings.MULTI_TENANCY,
        }
    )
