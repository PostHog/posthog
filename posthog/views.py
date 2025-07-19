from datetime import timedelta
import os
from functools import partial, wraps
from typing import Union
import uuid

from posthog.exceptions_capture import capture_exception
from django.apps import apps
from django.conf import settings
from django.contrib.admin.sites import site as admin_site
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required as base_login_required
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods


from posthog.cloud_utils import is_cloud
from posthog.email import is_email_available
from posthog.health import is_clickhouse_connected, is_kafka_connected
from posthog.models import Organization, User
from posthog.models.integration import SlackIntegration
from posthog.redis import get_client
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
from posthog.models.message_preferences import MessageCategory, MessageRecipientPreference, PreferenceStatus
from posthog.models.personal_api_key import (
    PersonalAPIKey,
    hash_key_value,
    PERSONAL_API_KEY_MODES_TO_TRY,
)


import structlog


logger = structlog.get_logger(__name__)


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
        capture_exception(err)
        return HttpResponse("Migrations are not up to date", status=status, content_type="text/plain")
    if status == 200:
        return HttpResponse("ok", status=status, content_type="text/plain")


def stats(request):
    stats_response: dict[str, Union[int, str]] = {}
    stats_response["worker_heartbeat"] = get_celery_heartbeat()
    return JsonResponse(stats_response)


def robots_txt(request):
    # Block all on self-hosted instances
    if not is_cloud():
        return HttpResponse("User-agent: *\nDisallow: /", content_type="text/plain")

    ROBOTS_TXT_CONTENT = """User-agent: *

# Block shared paths
Disallow: /shared_dashboard/
Disallow: /shared/

# Block URLs with sensitive query parameters
Disallow: /*?*email=
Disallow: /*?*organization_name=
Disallow: /*?*first_name=
Disallow: /*?*token=
Disallow: /*?*sharing_access_token=
Disallow: /*%40*
Disallow: /*@*

# Block authentication paths
Disallow: /verify_email/
Disallow: /authorize_and_redirect

# Block ingestion paths
Disallow: /e/
Disallow: /s/
Disallow: /i/
Disallow: /decide/
Disallow: /flags/
"""
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
    salesforce_client_id = settings.SALESFORCE_CONSUMER_KEY

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
        "data_warehouse_integrations": {
            "hubspot": {"client_id": hubspot_client_id},
            "salesforce": {"client_id": salesforce_client_id},
        },
        "object_storage": is_cloud() or is_object_storage_available(),
        "public_egress_ip_addresses": settings.PUBLIC_EGRESS_IP_ADDRESSES,
    }

    if settings.DEBUG or settings.E2E_TESTING:
        response["is_debug"] = True

    if settings.DEV_DISABLE_NAVIGATION_HOOKS:
        response["dev_disable_navigation_hooks"] = True

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


def get_redis_key_type_ttl_value_tuple(key: bytes, redis_client):
    """Get a tuple with a Redis key, type, and value from a Redis key."""
    redis_key = key.decode("utf-8")
    redis_type = redis_client.type(redis_key).decode("utf8")
    redis_ttl = redis_client.ttl(redis_key)

    if redis_ttl > 0:
        redis_ttl = timedelta(seconds=redis_ttl)

    if redis_type == "string":
        value = redis_client.get(key)

    elif redis_type == "hash":
        value = redis_client.hgetall(key)

    elif redis_type == "zset":
        value = redis_client.zrange(key, 0, -1)

    elif redis_type == "list":
        value = redis_client.lrange(key, 0, -1)

    elif redis_type == "set":
        value = redis_client.smembers(key)
    else:
        raise ValueError(f"Key {redis_key} has an unsupported type: {redis_type}")

    return (redis_key, redis_type, redis_ttl, value)


@staff_member_required
def redis_values_view(request: HttpRequest):
    """A Django admin view to list Redis key-value pairs."""
    if request.method != "GET":
        return HttpResponseNotAllowed(permitted_methods=["GET"])

    query = request.GET.get("q", None)
    if query == "":
        query = None

    keys_per_page = 50
    cursor = int(request.GET.get("c", 0))

    redis_client = get_client()
    next_cursor, key_list = redis_client.scan(cursor=cursor, count=keys_per_page, match=query)

    partial_get_redis_key = partial(get_redis_key_type_ttl_value_tuple, redis_client=redis_client)
    redis_keys = {
        redis_key: (redis_type, redis_ttl, value)
        for redis_key, redis_type, redis_ttl, value in map(partial_get_redis_key, key_list)
    }

    context = {
        **admin_site.each_context(request),
        **{
            "redis_keys": redis_keys,
            "query": query or "",
            "title": "Select Redis key to mutate",
            "cursor": cursor,
            "next_cursor": next_cursor,
            "keys_per_page": keys_per_page,
        },
    }

    return render(request, template_name="redis/values.html", context=context, status=200)


@staff_member_required
def api_key_search_view(request: HttpRequest):
    """A Django admin view to search for an API Key by value."""

    query = request.POST.get("q", None)
    if query is None:
        if request.method != "GET":
            return HttpResponseNotAllowed(permitted_methods=["GET"])
    else:
        if request.method != "POST":
            return HttpResponseNotAllowed(permitted_methods=["POST"])

    personal_api_key_object = None
    personal_api_key_hash_mode = None
    if query is not None and query.startswith("phx_"):
        for mode, iterations in PERSONAL_API_KEY_MODES_TO_TRY:
            secure_value = hash_key_value(query, mode=mode, iterations=iterations)
            try:
                personal_api_key_object = (
                    PersonalAPIKey.objects.select_related("user")
                    .filter(user__is_active=True)
                    .get(secure_value=secure_value)
                )
                personal_api_key_hash_mode = mode
                break

            except PersonalAPIKey.DoesNotExist:
                pass

    team_object = None
    team_object_key_type = None
    if query is not None and query.startswith("phs_"):
        Team = apps.get_model(app_label="posthog", model_name="Team")

        try:
            # don't use the cache so that we can differentiate btwn the primary and the backup key
            team_object = Team.objects.get(secret_api_token=query)
            team_object_key_type = "primary"

        except Team.DoesNotExist:
            pass

        try:
            team_object = Team.objects.get(secret_api_token_backup=query)
            team_object_key_type = "backup"

        except Team.DoesNotExist:
            pass

    context = {
        **admin_site.each_context(request),
        **{
            "query": query or "",
            "title": "Specify key to search",
            "personal_api_key_object": personal_api_key_object,
            "personal_api_key_hash_mode": personal_api_key_hash_mode,
            "team_object": team_object,
            "team_object_key_type": team_object_key_type,
        },
    }

    return render(request, template_name="api_key_search/values.html", context=context, status=200)


@require_http_methods(["GET"])
def preferences_page(request: HttpRequest, token: str) -> HttpResponse:
    """Render the preferences page for a given recipient token"""
    recipient, error = MessageRecipientPreference.validate_preferences_token(token)

    if error:
        return render(request, "message_preferences/error.html", {"error": error}, status=400)

    if not recipient:
        return render(request, "message_preferences/error.html", {"error": "Invalid recipient"}, status=400)

    # Only fetch active categories and their preferences
    categories = MessageCategory.objects.filter(deleted=False, team=recipient.team).order_by("name")
    preferences = recipient.get_all_preferences() if recipient else {}

    context = {
        "recipient": recipient,
        "categories": [
            {
                "id": cat.id,
                "name": cat.name,
                "description": cat.description,
                "opted_in": preferences.get(cat.id) == PreferenceStatus.OPTED_IN,
            }
            for cat in categories
        ],
        "token": token,  # Need to pass this back for the update endpoint
    }

    return render(request, "message_preferences/preferences.html", context)


@csrf_protect
@require_http_methods(["POST"])
def update_preferences(request: HttpRequest) -> JsonResponse:
    """Update preferences for a recipient"""
    token = request.POST.get("token")
    if not token:
        return JsonResponse({"error": "Missing token"}, status=400)

    recipient, error = MessageRecipientPreference.validate_preferences_token(token)
    if error:
        return JsonResponse({"error": error}, status=400)

    if not recipient:
        return JsonResponse({"error": "Invalid recipient"}, status=400)

    try:
        preferences = request.POST.getlist("preferences[]")
        # Convert to dict of category_id: opted_in
        for pref in preferences:
            category_id, opted_in = pref.split(":")
            status = PreferenceStatus.OPTED_IN if opted_in == "true" else PreferenceStatus.OPTED_OUT
            recipient.set_preference(uuid.UUID(category_id), status)

        return JsonResponse({"success": True})

    except Exception:
        return JsonResponse({"error": "Failed to update preferences"}, status=400)
