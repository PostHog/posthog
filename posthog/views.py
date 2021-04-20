import os
from functools import wraps
from typing import Dict, List, Union

import sentry_sdk
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required as base_login_required
from django.db import DEFAULT_DB_ALIAS, connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from rest_framework.exceptions import AuthenticationFailed

from posthog.ee import is_ee_enabled
from posthog.email import is_email_available
from posthog.models import User
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
from posthog.version import VERSION

from .utils import (
    get_available_social_auth_providers,
    get_available_timezones_with_offsets,
    get_celery_heartbeat,
    get_plugin_server_version,
)


def noop(*args, **kwargs) -> None:
    return None


try:
    from ee.models.license import get_licensed_users_available
except ImportError:
    get_licensed_users_available = noop


def login_required(view):
    base_handler = base_login_required(view)

    @wraps(view)
    def handler(request, *args, **kwargs):
        if not User.objects.exists():
            return redirect("/preflight")
        elif not request.user.is_authenticated and settings.AUTO_LOGIN:
            user = User.objects.first()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return base_handler(request, *args, **kwargs)

    return handler


def health(request):
    executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    status = 503 if plan else 200
    if status == 503:
        err = Exception("Migrations are not up to date. If this continues migrations have failed")
        sentry_sdk.capture_exception(err)
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

    metrics.append({"key": "posthog_version", "metric": "PostHog version", "value": VERSION})

    metrics.append(
        {
            "key": "analytics_database",
            "metric": "Analytics database in use",
            "value": "ClickHouse" if is_ee_enabled() else "Postgres",
        }
    )

    metrics.append(
        {
            "key": "ingestion_server",
            "metric": "Event ingestion via",
            "value": "Plugin Server" if settings.PLUGIN_SERVER_INGESTION else "Django",
        }
    )

    metrics.append({"key": "plugin_sever_alive", "metric": "Plugin server alive", "value": is_plugin_server_alive()})
    metrics.append(
        {
            "key": "plugin_sever_version",
            "metric": "Plugin server version",
            "value": get_plugin_server_version() or "unknown",
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

        if not is_ee_enabled():
            event_table_count = get_table_approx_count(Event._meta.db_table)
            event_table_size = get_table_size(Event._meta.db_table)

            element_table_count = get_table_approx_count(Element._meta.db_table)
            element_table_size = get_table_size(Element._meta.db_table)

            session_recording_event_table_count = get_table_approx_count(SessionRecordingEvent._meta.db_table)
            session_recording_event_table_size = get_table_size(SessionRecordingEvent._meta.db_table)

            metrics.append(
                {
                    "metric": "Postgres elements table size",
                    "value": f"{element_table_count} rows (~{element_table_size})",
                }
            )
            metrics.append(
                {"metric": "Postgres events table size", "value": f"{event_table_count} rows (~{event_table_size})"}
            )
            metrics.append(
                {
                    "metric": "Postgres session recording table size",
                    "value": f"{session_recording_event_table_count} rows (~{session_recording_event_table_size})",
                }
            )
    if is_ee_enabled():
        from ee.clickhouse.system_status import system_status

        metrics.extend(list(system_status()))

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
def preflight_check(request: HttpRequest) -> JsonResponse:

    response = {
        "django": True,
        "redis": is_redis_alive() or settings.TEST,
        "plugins": is_plugin_server_alive() or settings.TEST,
        "celery": is_celery_alive() or settings.TEST,
        "db": is_postgres_alive(),
        "initiated": User.objects.exists() if not settings.E2E_TESTING else False,  # Enables E2E testing of signup flow
        "cloud": settings.MULTI_TENANCY,
        "available_social_auth_providers": get_available_social_auth_providers(),
    }

    if request.user.is_authenticated:
        response = {
            **response,
            "ee_available": settings.EE_AVAILABLE,
            "ee_enabled": is_ee_enabled(),
            "db_backend": settings.PRIMARY_DB.value,
            "available_timezones": get_available_timezones_with_offsets(),
            "opt_out_capture": os.environ.get("OPT_OUT_CAPTURE", False),
            "posthog_version": VERSION,
            "email_service_available": is_email_available(with_absolute_urls=True),
            "is_debug": settings.DEBUG,
            "is_event_property_usage_enabled": settings.ASYNC_EVENT_PROPERTY_USAGE,
            "is_async_event_action_mapping_enabled": settings.ASYNC_EVENT_ACTION_MAPPING,
            "licensed_users_available": get_licensed_users_available(),
        }

    return JsonResponse(response)
