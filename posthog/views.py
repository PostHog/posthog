import os
from dataclasses import dataclass
from datetime import timedelta
from functools import wraps
from html import escape
from typing import Union
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django.apps import apps
from django.conf import settings
from django.contrib.admin.sites import site as admin_site
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required as base_login_required
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

import structlog

from posthog.cloud_utils import is_cloud
from posthog.email import is_email_available
from posthog.exceptions_capture import capture_exception
from posthog.health import is_clickhouse_connected, is_kafka_connected
from posthog.models import Organization, User
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.integration import SlackIntegration
from posthog.models.message_category import MessageCategory
from posthog.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)
from posthog.models.oauth import find_oauth_access_token, find_oauth_refresh_token
from posthog.models.personal_api_key import find_personal_api_key
from posthog.plugins.plugin_server_api import validate_messaging_preferences_token
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
    render_template,
)

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
        response = base_handler(request, *args, **kwargs)

        # Don't include next=/ in the login redirect URL since "/" is the default destination
        if hasattr(response, "url") and response.status_code == 302 and response.url.startswith(settings.LOGIN_URL):
            parsed_url = urlparse(response.url)
            search_params = parse_qs(parsed_url.query)
            if search_params.get("next") == ["/"]:
                del search_params["next"]
                response["Location"] = urlunparse(parsed_url._replace(query=urlencode(search_params)))

        return response

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


@xframe_options_exempt
def render_query(request: HttpRequest) -> HttpResponse:
    """Render a lightweight container for third parties to display PostHog visualizations."""
    from posthog.api.sharing import get_global_themes

    payload = {"query": None, "cachedResults": None, "context": None, "insight": None, "themes": get_global_themes()}
    return render_template("render_query.html", request, context={"render_query_payload": payload})


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

    if settings.TEST:
        response["is_test"] = True

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


MAX_VALUE_DISPLAY_LENGTH = 200


@dataclass
class RedisKeyInfo:
    key: str
    type: str
    ttl: timedelta | int
    size: str
    value: str
    full_value: str
    is_truncated: bool


def format_bytes(size_bytes: int) -> str:
    nbsp = "\u00a0"
    if size_bytes < 1024:
        return f"{size_bytes}{nbsp}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}{nbsp}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}{nbsp}MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f}{nbsp}GB"


def truncate_value(value, max_length: int = MAX_VALUE_DISPLAY_LENGTH) -> str:
    str_value = str(value)
    if len(str_value) <= max_length:
        return str_value
    return str_value[:max_length] + "..."


def get_redis_key_info(key: bytes, redis_client) -> RedisKeyInfo:
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

    memory_bytes = redis_client.memory_usage(redis_key) or 0
    full_value = str(value)
    is_truncated = len(full_value) > MAX_VALUE_DISPLAY_LENGTH

    return RedisKeyInfo(
        key=redis_key,
        type=redis_type,
        ttl=redis_ttl,
        size=format_bytes(memory_bytes),
        value=truncate_value(value),
        full_value=full_value,
        is_truncated=is_truncated,
    )


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

    redis_keys = [get_redis_key_info(key, redis_client) for key in key_list]

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


@csrf_protect
@staff_member_required
def redis_edit_ttl_view(request: HttpRequest):
    """A Django admin view to edit TTL of a Redis key."""
    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(permitted_methods=["GET", "POST"])

    redis_key = request.GET.get("key") or request.POST.get("key")
    if not redis_key:
        return redirect("redis_values")

    try:
        cursor = int(request.GET.get("c", "0"))
    except ValueError:
        cursor = 0
    query = request.GET.get("q", "")

    redis_client = get_client()

    if request.method == "POST":
        ttl_seconds_str = request.POST.get("ttl_seconds", "").strip()
        previous_ttl = redis_client.ttl(redis_key)

        if ttl_seconds_str == "":
            redis_client.persist(redis_key)
            activity = "ttl_removed"
            detail_name = f"Removed TTL from Redis key {redis_key}"
        else:
            try:
                ttl_seconds = int(ttl_seconds_str)
            except ValueError:
                return HttpResponse("Invalid TTL value: must be an integer", status=400)

            redis_client.expire(redis_key, ttl_seconds)
            activity = "ttl_updated"
            detail_name = f"Set TTL to {ttl_seconds}s on Redis key {redis_key}"

        user = request.user if request.user.is_authenticated else None
        organization_id = user.current_organization.id if user and user.current_organization else None

        log_activity(
            organization_id=organization_id,
            team_id=None,
            user=user,
            was_impersonated=False,
            item_id=redis_key,
            scope="Admin",
            activity=activity,
            detail=Detail(
                name=detail_name,
                short_id=redis_key,
                type=f"previous_ttl:{previous_ttl}",
            ),
        )

        params: dict[str, str | int] = {"c": cursor}
        if query:
            params["q"] = query
        return redirect(f"/admin/redisvalues?{urlencode(params)}")

    current_ttl = redis_client.ttl(redis_key)

    if current_ttl == -2:
        return HttpResponse(f"Redis key not found: {escape(redis_key)}", status=404)

    context = {
        **admin_site.each_context(request),
        **{
            "redis_key": redis_key,
            "current_ttl": current_ttl if current_ttl > 0 else None,
            "cursor": cursor,
            "query": query,
            "title": f"Edit TTL for {redis_key}",
        },
    }

    return render(request, template_name="redis/edit_ttl.html", context=context, status=200)


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
        result = find_personal_api_key(query)
        if result is not None:
            personal_api_key_object, personal_api_key_hash_mode = result

    team_object = None
    team_object_key_type = None
    if query is not None and query.startswith("phs_"):
        Team = apps.get_model(app_label="posthog", model_name="Team")

        try:
            # don't use the cache so that we can differentiate btwn the primary and the backup key
            team_object = Team.objects.get(Q(secret_api_token=query) | Q(secret_api_token_backup=query))
            team_object_key_type = "primary" if team_object.secret_api_token == query else "backup"

        except Team.DoesNotExist:
            pass

    oauth_access_token_object = None
    if query is not None and query.startswith("pha_"):
        oauth_access_token_object = find_oauth_access_token(query)

    oauth_refresh_token_object = None
    if query is not None and query.startswith("phr_"):
        oauth_refresh_token_object = find_oauth_refresh_token(query)

    context = {
        **admin_site.each_context(request),
        **{
            "query": query or "",
            "title": "Specify key to search",
            "personal_api_key_object": personal_api_key_object,
            "personal_api_key_hash_mode": personal_api_key_hash_mode,
            "team_object": team_object,
            "team_object_key_type": team_object_key_type,
            "oauth_access_token_object": oauth_access_token_object,
            "oauth_refresh_token_object": oauth_refresh_token_object,
        },
    }

    return render(request, template_name="api_key_search/values.html", context=context, status=200)


@require_http_methods(["GET"])
def preferences_page(request: HttpRequest, token: str) -> HttpResponse:
    """Render the preferences page for a given recipient token"""
    response = validate_messaging_preferences_token(token)
    if response.status_code != 200:
        error_msg = response.json().get("error", "Invalid recipient token")
        return render(request, "message_preferences/error.html", {"error": error_msg}, status=400)

    data = response.json()
    if not data.get("valid"):
        return render(request, "message_preferences/error.html", {"error": "Invalid recipient token"}, status=400)

    team_id = data.get("team_id")
    identifier = data.get("identifier")
    if not team_id or not identifier:
        return render(request, "message_preferences/error.html", {"error": "Invalid recipient"}, status=400)

    try:
        recipient = MessageRecipientPreference.objects.get(team_id=team_id, identifier=identifier)
    except MessageRecipientPreference.DoesNotExist:
        # A first-time preferences page visitor will not have a recipient in Postgres yet.
        recipient = None

    # Only fetch active categories and their preferences
    categories = MessageCategory.objects.filter(deleted=False, team=team_id, category_type="marketing").order_by("name")
    preferences = recipient.get_all_preferences() if recipient else {}

    context = {
        "recipient": recipient,
        "categories": [
            {
                "id": cat.id,
                "name": cat.name,
                "description": cat.public_description,
                "status": preferences.get(str(cat.id), PreferenceStatus.NO_PREFERENCE),
            }
            for cat in categories
        ],
        "token": token,
    }

    return render(request, "message_preferences/preferences.html", context)


@csrf_protect
@require_http_methods(["POST"])
def update_preferences(request: HttpRequest) -> JsonResponse:
    """Update preferences for a recipient"""
    token = request.POST.get("token")
    if not token:
        return JsonResponse({"error": "Missing token"}, status=400)

    response = validate_messaging_preferences_token(token)
    if response.status_code != 200:
        error_msg = response.json().get("error", "Invalid recipient token")
        return JsonResponse({"error": error_msg}, status=400)

    data = response.json()
    if not data.get("valid"):
        return JsonResponse({"error": "Invalid recipient token"}, status=400)
    team_id = data.get("team_id")
    identifier = data.get("identifier")
    if not team_id or not identifier:
        return JsonResponse({"error": "Invalid recipient"}, status=400)

    recipient = None

    try:
        recipient = MessageRecipientPreference.objects.get(team_id=team_id, identifier=identifier)
    except MessageRecipientPreference.DoesNotExist:
        recipient = MessageRecipientPreference(team_id=team_id, identifier=identifier)

    try:
        preferences = request.POST.getlist("preferences[]")
        # Convert to dict of category_id: status
        preferences_dict = {}
        all_opted_out = True

        for pref in preferences:
            category_id, opted_in = pref.split(":")

            if opted_in not in ["true", "false"]:
                return JsonResponse({"error": "Preference values must be 'true' or 'false'"}, status=400)

            status = PreferenceStatus.OPTED_IN if opted_in == "true" else PreferenceStatus.OPTED_OUT
            preferences_dict[category_id] = status.value

            if status == PreferenceStatus.OPTED_IN:
                all_opted_out = False

        # If all preferences are opted out, add the "$all" preference
        if all_opted_out and preferences_dict:
            preferences_dict[ALL_MESSAGE_PREFERENCE_CATEGORY_ID] = PreferenceStatus.OPTED_OUT.value

        # Update all preferences with a single DB write
        recipient.preferences = preferences_dict
        recipient.save()

        return JsonResponse({"success": True})

    except Exception as e:
        capture_exception(e)
        return JsonResponse({"error": "Failed to update preferences"}, status=400)
