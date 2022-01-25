import os
from functools import wraps
from typing import Dict, Union

import sentry_sdk
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required as base_login_required
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache

from posthog.email import is_email_available
from posthog.models import Organization, User
from posthog.utils import (
    get_available_social_auth_providers,
    get_available_timezones_with_offsets,
    get_can_create_org,
    get_celery_heartbeat,
    get_instance_realm,
    is_celery_alive,
    is_plugin_server_alive,
    is_postgres_alive,
    is_redis_alive,
)
from ee.kafka_client.client import KafkaProducer
from posthog.version import VERSION

ROBOTS_TXT_CONTENT = (
    "User-agent: *\nDisallow: /shared_dashboard/" if settings.MULTI_TENANCY else "User-agent: *\nDisallow: /"
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
    """
    Validate that everything this process need to operate correctly is in place.
    Returns a dict of checks to boolean status, returning 503 status if any of
    them is non-True
    """
    migrations_uptodate = health_migrations(request)
    kafka_connected = health_kafka(request)

    if migrations_uptodate == False:
        # NOTE: before adding kafka to this health check, we were just checking
        # migrations, sending the below sentry error, and returning 503. I've
        # left this sentry error here but it can probably be removed, and issues
        # with migration alerting managed elsewhere.
        err = Exception("Migrations are not up to date. If this continues migrations have failed")
        sentry_sdk.capture_exception(err)

    status = 200 if migrations_uptodate and kafka_connected else 500
    return JsonResponse({"migrations_uptodate": migrations_uptodate, "kafka_connected": kafka_connected}, status=status)


def health_kafka(request) -> bool:
    """
    Check that we can reach Kafka,

    Returns `True` if connected, `False` otherwise.

    NOTE: we are only checking the Producer here, as currently this process
    does not Consume from Kafka.
    """
    return KafkaProducer().bootstrap_connected()


def health_migrations(request) -> bool:
    """
    Check that all migrations that the running version of the code knows about
    have been applied.

    Returns `True` if so, `False` otherwise
    """
    executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    return False if plan else True


def stats(request):
    stats_response: Dict[str, Union[int, str]] = {}
    stats_response["worker_heartbeat"] = get_celery_heartbeat()
    return JsonResponse(stats_response)


def robots_txt(request):
    return HttpResponse(ROBOTS_TXT_CONTENT, content_type="text/plain")


@never_cache
def preflight_check(request: HttpRequest) -> JsonResponse:
    response = {
        "django": True,
        "redis": is_redis_alive() or settings.TEST,
        "plugins": is_plugin_server_alive() or settings.TEST,
        "celery": is_celery_alive() or settings.TEST,
        "db": is_postgres_alive(),
        "initiated": Organization.objects.exists(),
        "cloud": settings.MULTI_TENANCY,
        "demo": settings.DEMO,
        "realm": get_instance_realm(),
        "available_social_auth_providers": get_available_social_auth_providers(),
        "can_create_org": get_can_create_org(),
        "email_service_available": is_email_available(with_absolute_urls=True),
    }

    if request.user.is_authenticated:
        response = {
            **response,
            "db_backend": settings.PRIMARY_DB.value,
            "available_timezones": get_available_timezones_with_offsets(),
            "opt_out_capture": os.environ.get("OPT_OUT_CAPTURE", False),
            "posthog_version": VERSION,
            "is_debug": settings.DEBUG,
            "is_event_property_usage_enabled": settings.ASYNC_EVENT_PROPERTY_USAGE,
            "licensed_users_available": get_licensed_users_available(),
            "site_url": settings.SITE_URL,
            "instance_preferences": settings.INSTANCE_PREFERENCES,
        }

    return JsonResponse(response)
