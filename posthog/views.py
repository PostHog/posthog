import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import wraps
from typing import Literal, Union, cast
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required as base_login_required
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound, HttpResponseServerError, JsonResponse
from django.shortcuts import redirect, render
from django.template import loader
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import requires_csrf_token

import structlog
from opentelemetry import trace
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest, multiprocess

from posthog.auth import AUTH_BRAND_COOKIE, apply_auth_brand_cookie, normalize_auth_brand
from posthog.cache_utils import cache_for
from posthog.cloud_utils import is_cloud, is_hobby
from posthog.credentials_service.callers import CredentialsCaller
from posthog.credentials_service.errors import CredentialsServiceFailure
from posthog.credentials_service.settings_fallback import get_many_or_settings
from posthog.email import is_email_available
from posthog.exceptions_capture import capture_exception
from posthog.health import is_clickhouse_connected, is_kafka_connected
from posthog.helpers.dev_login import is_dev_login_allowed
from posthog.models import Organization, User
from posthog.models.instance_setting import get_instance_settings
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


def llms_txt(request: HttpRequest) -> HttpResponse:
    if is_hobby():
        return HttpResponseNotFound()

    return render(request, "llms_txt.md", {"site_url": settings.SITE_URL}, content_type="text/markdown; charset=utf-8")


def not_found(request: HttpRequest) -> HttpResponse:
    return HttpResponseNotFound()


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


PREFLIGHT_OAUTH_CLIENT_ID_KEYS = ["HUBSPOT_APP_CLIENT_ID", "SALESFORCE_CONSUMER_KEY"]


@cache_for(timedelta(minutes=5))
def _preflight_oauth_client_ids() -> dict[str, str]:
    try:
        return get_many_or_settings(PREFLIGHT_OAUTH_CLIENT_ID_KEYS, CredentialsCaller.INTEGRATIONS)
    except CredentialsServiceFailure:
        logger.warning("preflight.credentials_service_unavailable", keys=PREFLIGHT_OAUTH_CLIENT_ID_KEYS)
        return {key: cast(str, getattr(settings, key)) for key in PREFLIGHT_OAUTH_CLIENT_ID_KEYS}


def _preflight_oauth_client_id(key: Literal["HUBSPOT_APP_CLIENT_ID", "SALESFORCE_CONSUMER_KEY"]) -> str:
    return _preflight_oauth_client_ids()[key]


@cache_for(timedelta(minutes=5))
def _preflight_slack_instance_client_id() -> str:
    return cast(str, get_instance_settings(["SLACK_APP_CLIENT_ID"])["SLACK_APP_CLIENT_ID"] or "")


def _preflight_slack_client_id(instance_setting: str) -> str:
    with tracer.start_as_current_span("preflight.slack_config_main"):
        return SlackIntegration.slack_client_id(instance_setting)


@never_cache
def preflight_check(request: HttpRequest) -> JsonResponse:
    # Read the database-backed fallback on the request thread, then resolve independent credential
    # groups concurrently so a service timeout costs at most one request timeout. HubSpot and
    # Salesforce share one batch request.
    slack_instance_client_id = _preflight_slack_instance_client_id()
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="preflight-credentials") as executor:
        slack_client_id_future = executor.submit(_preflight_slack_client_id, slack_instance_client_id)
        oauth_client_ids_future = executor.submit(_preflight_oauth_client_ids)
        slack_client_id = slack_client_id_future.result()
        oauth_client_ids = oauth_client_ids_future.result()

    hubspot_client_id = oauth_client_ids["HUBSPOT_APP_CLIENT_ID"]
    salesforce_client_id = oauth_client_ids["SALESFORCE_CONSUMER_KEY"]

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
            "cohort_csv_upload_max_bytes": settings.COHORT_CSV_UPLOAD_MAX_BYTES,
            "webmcp_available": webmcp_api.is_available(),
        }

    return JsonResponse(response)


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
