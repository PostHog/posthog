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
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, HttpResponseServerError, JsonResponse
from django.shortcuts import redirect, render
from django.template import loader
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_protect, requires_csrf_token

import structlog
from opentelemetry import trace
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest, multiprocess

from posthog.api.secret_revocation import NON_PERSONAL_SECRET_PREFIXES
from posthog.auth import AUTH_BRAND_COOKIE, apply_auth_brand_cookie, normalize_auth_brand
from posthog.cloud_utils import is_cloud
from posthog.email import is_email_available
from posthog.exceptions_capture import capture_exception
from posthog.health import is_clickhouse_connected, is_kafka_connected
from posthog.helpers.dev_login import is_dev_login_allowed
from posthog.models import Organization, User
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.integration import SlackIntegration
from posthog.models.oauth import find_oauth_access_token, find_oauth_refresh_token
from posthog.models.personal_api_key import find_personal_api_key
from posthog.models.project_secret_api_key import find_project_secret_api_key
from posthog.models.utils import (
    OAUTH_ACCESS_TOKEN_PREFIX,
    OAUTH_REFRESH_TOKEN_PREFIX,
    PROJECT_API_TOKEN_PREFIX,
    SECRET_API_TOKEN_PREFIX,
)
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
tracer = trace.get_tracer(__name__)


def _traced(name: str, fn, *args, **kwargs):
    with tracer.start_as_current_span(name):
        return fn(*args, **kwargs)


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
        # Dev-only: in cloud-OAuth mode the session is client-side, so serve without a local login
        # (the SPA uses its bearer token). DEBUG-gated, so prod gating is unchanged.
        if settings.DEBUG and request.COOKIES.get("ph_oauth_mode"):
            return view(request, *args, **kwargs)
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

        return apply_auth_brand_cookie(request, response)

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
Disallow: /toolbar_oauth/

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
    with tracer.start_as_current_span("preflight.slack_config_main"):
        slack_client_id = SlackIntegration.slack_config().get("SLACK_APP_CLIENT_ID")
    hubspot_client_id = settings.HUBSPOT_APP_CLIENT_ID
    salesforce_client_id = settings.SALESFORCE_CONSUMER_KEY

    in_cloud = is_cloud()

    response = {
        "django": True,
        "redis": in_cloud or _traced("preflight.is_redis_alive", is_redis_alive) or settings.TEST,
        "plugins": in_cloud or _traced("preflight.is_plugin_server_alive", is_plugin_server_alive) or settings.TEST,
        "celery": in_cloud or _traced("preflight.is_celery_alive", is_celery_alive) or settings.TEST,
        "clickhouse": in_cloud
        or _traced("preflight.is_clickhouse_connected", is_clickhouse_connected)
        or settings.TEST,
        "kafka": in_cloud or _traced("preflight.is_kafka_connected", is_kafka_connected),
        "db": in_cloud or _traced("preflight.is_postgres_alive", is_postgres_alive),
        "initiated": in_cloud or _traced("preflight.organization_exists", Organization.objects.exists),
        "cloud": in_cloud,
        "demo": settings.DEMO,
        "realm": get_instance_realm(),
        "region": get_instance_region(),
        "available_social_auth_providers": _traced(
            "preflight.available_social_auth_providers", get_instance_available_sso_providers
        ),
        "can_create_org": _traced("preflight.can_create_org", get_can_create_org, request.user),
        "email_service_available": in_cloud
        or _traced("preflight.is_email_available", is_email_available, with_absolute_urls=True),
        "slack_service": {
            "available": bool(slack_client_id),
            "client_id": slack_client_id or None,
        },
        "data_warehouse_integrations": {
            "hubspot": {"client_id": hubspot_client_id},
            "salesforce": {"client_id": salesforce_client_id},
        },
        "object_storage": in_cloud or _traced("preflight.is_object_storage_available", is_object_storage_available),
        "public_egress_ip_addresses": settings.PUBLIC_EGRESS_IP_ADDRESSES,
        "wizard_cloud_run_available": bool(settings.WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID),
    }
    auth_brand = normalize_auth_brand(request.COOKIES.get(AUTH_BRAND_COOKIE))
    if auth_brand:
        response["auth_brand"] = auth_brand

    if settings.DEBUG or settings.E2E_TESTING:
        response["is_debug"] = True

    if is_dev_login_allowed():
        response["allow_dev_login"] = True

    if settings.TEST:
        response["is_test"] = True

    if settings.DEV_DISABLE_NAVIGATION_HOOKS:
        response["dev_disable_navigation_hooks"] = True

    if request.user.is_authenticated:
        from products.webmcp.backend.facade import (  # noqa: PLC0415 - circular via posthog.api.oauth, which imports this module
            api as webmcp_api,
        )

        response = {
            **response,
            "available_timezones": _traced("preflight.available_timezones", get_available_timezones_with_offsets),
            "opt_out_capture": os.environ.get("OPT_OUT_CAPTURE", False),
            "licensed_users_available": _traced("preflight.licensed_users_available", get_licensed_users_available)
            if not in_cloud
            else None,
            "openai_available": bool(os.environ.get("OPENAI_API_KEY")),
            # Max runs on Anthropic, so it needs its own signal — otherwise self-hosted instances
            # render the assistant but fail at call time with no key configured.
            "anthropic_available": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "site_url": settings.SITE_URL,
            "instance_preferences": settings.INSTANCE_PREFERENCES,
            "buffer_conversion_seconds": settings.BUFFER_CONVERSION_SECONDS,
            "webmcp_available": webmcp_api.is_available(),
        }

    return JsonResponse(response)


MAX_VALUE_DISPLAY_LENGTH = 200


@dataclass
class RedisKeySnapshot:
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


def get_redis_key_info(key: bytes, redis_client) -> RedisKeySnapshot:
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

    return RedisKeySnapshot(
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
        query = query.strip()

    personal_api_key_object = None
    personal_api_key_hash_mode = None
    # Legacy personal API keys predate the phx_ prefix, so any query without another known
    # prefix is also treated as a personal key candidate (matching authentication behavior).
    non_personal_api_key_prefixes = (*NON_PERSONAL_SECRET_PREFIXES, PROJECT_API_TOKEN_PREFIX)
    if query and not query.startswith(non_personal_api_key_prefixes):
        result = find_personal_api_key(query)
        if result is not None:
            personal_api_key_object, personal_api_key_hash_mode = result

    project_secret_api_key_object = None
    team_object = None
    team_object_key_type = None
    if query is not None and query.startswith(SECRET_API_TOKEN_PREFIX):
        project_secret_api_key_object = find_project_secret_api_key(query)

        Team = apps.get_model(app_label="posthog", model_name="Team")

        try:
            # don't use the cache so that we can differentiate btwn the primary and the backup key
            team_object = Team.objects.get(Q(secret_api_token=query) | Q(secret_api_token_backup=query))
            team_object_key_type = "primary" if team_object.secret_api_token == query else "backup"

        except Team.DoesNotExist:
            pass

    oauth_access_token_object = None
    if query is not None and query.startswith(OAUTH_ACCESS_TOKEN_PREFIX):
        oauth_access_token_object = find_oauth_access_token(query)

    oauth_refresh_token_object = None
    if query is not None and query.startswith(OAUTH_REFRESH_TOKEN_PREFIX):
        oauth_refresh_token_object = find_oauth_refresh_token(query)

    context = {
        **admin_site.each_context(request),
        **{
            "query": query or "",
            "title": "Specify key to search",
            "personal_api_key_object": personal_api_key_object,
            "personal_api_key_hash_mode": personal_api_key_hash_mode,
            "project_secret_api_key_object": project_secret_api_key_object,
            "team_object": team_object,
            "team_object_key_type": team_object_key_type,
            "oauth_access_token_object": oauth_access_token_object,
            "oauth_refresh_token_object": oauth_refresh_token_object,
        },
    }

    return render(request, template_name="api_key_search/values.html", context=context, status=200)


@xframe_options_exempt
@never_cache
def replay_player_frame(request: HttpRequest) -> HttpResponse:
    """Empty shell the replay player mounts rrweb into.

    rrweb builds its own `about:blank` iframe, and a frame on a local scheme inherits its parent's
    whole policy, report-uri included. Mounting rrweb here rather than in the app document puts a
    real document in that inheritance chain, so a recorded page is judged against this frame's
    policy instead of the app's. CSPMiddleware supplies that policy.
    """
    return render(request, "replay_player_frame/index.html")


@requires_csrf_token
def handler500(request: HttpRequest) -> HttpResponse:
    """
    500 error handler.

    Templates: :template:`500.html`
    Context: request
    """
    template = loader.get_template("500.html")
    return HttpResponseServerError(template.render({"request": request}, request))


def metrics_view(request: HttpRequest) -> HttpResponse:
    """Metrics endpoint that aggregates from all processes using multiprocess mode."""
    registry = CollectorRegistry()
    # If prometheus_multiproc_dir is set, collect from all processes
    if "prometheus_multiproc_dir" in os.environ or "PROMETHEUS_MULTIPROC_DIR" in os.environ:
        multiprocess.MultiProcessCollector(registry)
    else:
        # Fallback to default registry if multiprocess not configured
        registry = REGISTRY

    metrics_output = generate_latest(registry)
    return HttpResponse(metrics_output, content_type="text/plain; charset=utf-8; version=0.0.4")
