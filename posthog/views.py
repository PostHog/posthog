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

from posthog.cloud_utils import is_cloud
from posthog.email import is_email_available
from posthog.health import is_clickhouse_connected, is_kafka_connected
from posthog.models import Organization, User
from posthog.models.integration import SlackIntegration
from posthog.utils import (
    get_available_timezones_with_offsets,
    get_can_create_org,
    get_celery_heartbeat,
    get_instance_available_sso_providers,
    get_instance_realm,
    get_instance_region,
    is_celery_alive,
    is_object_storage_available,
    is_plugin_server_alive,
    is_postgres_alive,
    is_redis_alive,
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
            user = User.objects.filter(is_active=True).first()
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


def robots_txt(request):
    ROBOTS_TXT_CONTENT = "User-agent: *\nDisallow: /shared_dashboard/" if is_cloud() else "User-agent: *\nDisallow: /"
    return HttpResponse(ROBOTS_TXT_CONTENT, content_type="text/plain")


def security_txt(request):
    SECURITY_TXT_CONTENT = """
        Contact: mailto:engineering@posthog.com
        Hiring: https://posthog.com/careers
        Expires: 2024-03-14T00:00:00.000Z
        """
    return HttpResponse(SECURITY_TXT_CONTENT, content_type="text/plain")


@never_cache
def preflight_check(request: HttpRequest) -> JsonResponse:
    slack_client_id = SlackIntegration.slack_config().get("SLACK_APP_CLIENT_ID")
    hubspot_client_id = settings.HUBSPOT_APP_CLIENT_ID

    response = {
        "django": True,
        "redis": is_cloud() or is_redis_alive() or settings.TEST,
        "plugins": is_cloud() or is_plugin_server_alive() or settings.TEST,
        "celery": is_cloud() or is_celery_alive() or settings.TEST,
        "clickhouse": is_cloud() or is_clickhouse_connected() or settings.TEST,
        "kafka": is_cloud() or is_kafka_connected() or settings.TEST,
        "db": is_cloud() or is_postgres_alive(),
        "initiated": is_cloud() or Organization.objects.exists(),
        "cloud": is_cloud(),
        "demo": settings.DEMO,
        "realm": get_instance_realm(),
        "region": get_instance_region(),
        "available_social_auth_providers": get_instance_available_sso_providers(),
        "can_create_org": get_can_create_org(request.user),
        "email_service_available": is_cloud() or is_email_available(with_absolute_urls=True),
        "slack_service": {
            "available": bool(slack_client_id),
            "client_id": slack_client_id or None,
        },
        "data_warehouse_integrations": {"hubspot": {"client_id": hubspot_client_id}},
        "object_storage": is_cloud() or is_object_storage_available(),
    }

    if settings.DEBUG or settings.E2E_TESTING:
        response["is_debug"] = True

    if request.user.is_authenticated:
        response = {
            **response,
            "available_timezones": get_available_timezones_with_offsets(),
            "opt_out_capture": os.environ.get("OPT_OUT_CAPTURE", False),
            "licensed_users_available": get_licensed_users_available() if not is_cloud() else None,
            "openai_available": bool(os.environ.get("OPENAI_API_KEY")),
            "site_url": settings.SITE_URL,
            "instance_preferences": settings.INSTANCE_PREFERENCES,
            "buffer_conversion_seconds": settings.BUFFER_CONVERSION_SECONDS,
        }

    return JsonResponse(response)
