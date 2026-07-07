from typing import Any, cast
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, HttpResponseServerError
from django.template import loader
from django.urls import include, path, re_path
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie, requires_csrf_token
from django.views.generic.base import RedirectView

import structlog
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from prometheus_client import CollectorRegistry, generate_latest, multiprocess
from two_factor.urls import urlpatterns as tf_urls

from posthog.api import (
    api_not_found,
    authentication,
    github,
    playwright_setup,
    report,
    router,
    sharing,
    signup,
    site_app,
    two_factor_reset,
    unsubscribe,
    uploaded_media,
    user,
)
from posthog.api.github_callback.views import github_oauth_callback, github_setup_callback
from posthog.api.oauth.connected_apps import ConnectedAppsViewSet
from posthog.api.oauth.raycast_metadata import RAYCAST_METADATA_PATH, RaycastClientMetadataView
from posthog.api.oauth.wizard_metadata import WIZARD_METADATA_PATH, WizardClientMetadataView
from posthog.api.query import progress
from posthog.api.sdk_health import sdk_health
from posthog.api.two_factor_qrcode import CacheAwareQRGeneratorView
from posthog.api.utils import hostname_in_allowed_url_list
from posthog.api.web_experiment import web_experiments
from posthog.api.zendesk_orgcheck import ensure_zendesk_organization
from posthog.constants import PERMITTED_FORUM_DOMAINS
from posthog.models import User
from posthog.models.instance_setting import get_instance_setting
from posthog.oauth2_urls import urlpatterns as oauth2_urls
from posthog.temporal.codec_server import decode_payloads

from products.ai_observability.backend.api.personal_spend import personal_spend_eu_redirect
from products.cdp.backend.api import hog_function_template
from products.data_warehouse.backend.presentation.views.public_source_configs import PublicSourceConfigViewSet
from products.demo.backend.facade.api import demo_route
from products.early_access_features.backend.api import early_access_features
from products.legal_documents.backend.presentation.webhook import legal_document_pandadoc_webhook
from products.messaging.backend.api.customerio_webhook import CustomerIOWebhookView
from products.messaging.backend.api.push_subscriptions import push_subscriptions
from products.notebooks.backend.facade.sql_v2 import notebook_sql_v2_callback, notebook_sql_v2_data_plane
from products.product_tours.backend.api import product_tours
from products.signals.backend import views as signals_views
from products.signals.backend.views import SignalUserAutonomyConfigView as signals_user_autonomy_view
from products.slack_app.backend.api import (
    posthog_code_event_handler,
    posthog_code_interactivity_handler,
    slack_workspace_claims_view,
)
from products.slack_app.backend.views import (
    slack_app_command_handler,
    slack_user_link_authorize,
    slack_user_link_callback,
)
from products.surveys.backend.api.survey import public_survey_page
from products.tasks.backend.facade.agent_proxy import agent_proxy_callback
from products.user_interviews.backend.presentation.webhooks import (
    start_call as user_interviews_start_call,
    vapi_webhook,
)
from products.workflows.backend.api import hog_flow, hog_flow_template

from .utils import opt_slash_path, render_template
from .views import (
    health,
    login_required,
    preferences_page,
    preflight_check,
    render_query,
    robots_txt,
    security_txt,
    stats,
    update_preferences,
)

logger = structlog.get_logger(__name__)

ee_urlpatterns: list[Any] = []
try:
    from ee.urls import (
        extend_api_router,
        urlpatterns as ee_urlpatterns,
    )
except ImportError:
    if settings.DEBUG:
        logger.warn(f"Could not import ee.urls", exc_info=True)
    pass
else:
    extend_api_router()


@csrf_exempt
def github_webhook(request: HttpRequest) -> HttpResponse:
    """Unified GitHub App webhook dispatcher.

    Verifies the HMAC-SHA256 signature once, parses JSON once, then routes
    by ``X-GitHub-Event`` to the appropriate product handler.
    """
    import json

    from products.tasks.backend.facade.webhooks import get_github_webhook_secret, verify_github_signature

    if request.method != "POST":
        return HttpResponse(status=405)

    secret = get_github_webhook_secret()
    if not secret:
        return HttpResponse("Webhook not configured", status=500)

    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_github_signature(request.body, signature, secret):
        return HttpResponse("Invalid signature", status=403)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    event_type = request.headers.get("X-GitHub-Event", "")

    if event_type in ("issues", "issue_comment"):
        from products.conversations.backend.api.github_events import dispatch_github_event

        return dispatch_github_event(request, event_type, payload)

    if event_type == "pull_request":
        from products.tasks.backend.facade.webhooks import handle_pull_request_event

        return handle_pull_request_event(payload)

    if event_type == "installation":
        from posthog.api.github_callback.installation_events import handle_installation_event

        return handle_installation_event(payload)

    return HttpResponse(status=200)


@requires_csrf_token
def handler500(request):
    """
    500 error handler.

    Templates: :template:`500.html`
    Context: request
    """
    template = loader.get_template("500.html")
    return HttpResponseServerError(template.render({"request": request}, request))


APP_POSTHOG_HOST = "app.posthog.com"
# Canonical per-region hosts a `ph_current_instance` cookie is allowed to resolve to.
# Restricting to this set keeps the cookie from being turned into an open redirect.
_REGION_HOSTS = {"us.posthog.com", "eu.posthog.com"}


def region_host_from_current_instance(cookie_value: str | None) -> str | None:
    """Map a `ph_current_instance` cookie (an instance SITE_URL) to its canonical region
    host, or None when it isn't a recognized cloud region. Mirrors the frontend
    `cleanedCookieSubdomain` in RedirectToLoggedInInstance.tsx — the value is sometimes
    wrapped in quotes by the cookie serializer, so strip those before parsing."""
    if not cookie_value:
        return None
    hostname = urlparse(cookie_value.replace('"', "")).hostname
    return hostname if hostname in _REGION_HOSTS else None


def app_region_redirect(request: HttpRequest) -> HttpResponseRedirect | None:
    """For `app.posthog.com` page loads, send the browser to the region the user is
    actually logged into (per the `ph_current_instance` cookie), preserving the path and
    query. Falls back to the `REDIRECT_APP_TO_US` instance setting when there's no region
    cookie. Returns None when no redirect applies so callers render normally.

    This has to run before the `login_required` auth gate: `app.posthog.com` is the US
    backend, so an EU user hitting a deep link like /organization/billing is otherwise
    bounced to /login on US first, and only the login page honors the cookie."""
    if request.method not in ("GET", "HEAD"):
        return None
    if request.get_host().split(":")[0] != APP_POSTHOG_HOST:
        return None

    target_host = region_host_from_current_instance(request.COOKIES.get("ph_current_instance"))
    if target_host is None and get_instance_setting("REDIRECT_APP_TO_US"):
        target_host = "us.posthog.com"
    if target_host is None:
        return None

    url = "https://{}{}".format(target_host, request.get_full_path())
    if url_has_allowed_host_and_scheme(url, target_host, True):
        return HttpResponseRedirect(url)
    return None


@ensure_csrf_cookie
def _render_home(request, *args, **kwargs):
    return render_template("index.html", request)


# Wrapped once at import time (as `login_required(home)` used to be) so the catch-all
# authenticated route doesn't rebuild the wrapper on every request.
_login_required_render_home = login_required(_render_home)


def home(request, *args, **kwargs):
    """Entrypoint for the unauthenticated frontend routes (login, signup, …). Runs the
    cross-region redirect before rendering so `app.posthog.com` visitors land on their
    logged-in region (see `app_region_redirect`)."""
    region_redirect = app_region_redirect(request)
    if region_redirect is not None:
        return region_redirect
    return _render_home(request, *args, **kwargs)


def home_with_region_redirect(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
    """Catch-all entrypoint for authenticated frontend routes. The cross-region redirect
    runs before `login_required` so `app.posthog.com` deep links reach the right region
    without a detour through the login page (see `app_region_redirect`). It wraps
    `_render_home` rather than `home` so the redirect check runs exactly once per request."""
    region_redirect = app_region_redirect(request)
    if region_redirect is not None:
        return region_redirect
    return _login_required_render_home(request, *args, **kwargs)


_CONNECT_REDIRECT_ALLOWED_KINDS = {"github", "slack", "linear"}
# Surfaces allowed to start a connect flow and be returned to afterwards (see
# posthog/api/github_callback/types.py APP_CONNECT_FROM_VALUES, plus Slack).
_CONNECT_REDIRECT_ALLOWED_SURFACES = {"posthog_code", "posthog_mobile", "slack"}


def integration_connect_redirect(request: HttpRequest, kind: str) -> HttpResponse:
    """Login-gated entry point for starting an integration OAuth connect from an external surface
    (a Slack message, the desktop app, etc.). Wrapped in ``login_required`` so unauthenticated users
    are bounced to login and resume here, then redirected into the existing ``integrations/authorize``
    flow with a ``connect_from``-tagged return page. ``next`` is constructed internally (never taken
    from the query) so this can't be used as an open redirect."""
    if kind not in _CONNECT_REDIRECT_ALLOWED_KINDS:
        return HttpResponse("Unsupported integration kind", status=400)
    connect_from = request.GET.get("connect_from", "")
    if connect_from not in _CONNECT_REDIRECT_ALLOWED_SURFACES:
        return HttpResponse("Unsupported connect_from", status=400)
    project_id = request.GET.get("project_id") or getattr(request.user, "current_team_id", None)
    if not project_id or not str(project_id).isdigit():
        return HttpResponse("Missing or invalid project_id", status=400)

    next_path = "/account-connected/{}-integration?{}".format(
        kind, urlencode({"provider": kind, "project_id": project_id, "connect_from": connect_from})
    )
    authorize_url = "/api/environments/{}/integrations/authorize/?{}".format(
        project_id, urlencode({"kind": kind, "next": next_path})
    )
    return HttpResponseRedirect(authorize_url)


def authorize_and_redirect(request: HttpRequest) -> HttpResponse:
    if not request.GET.get("redirect"):
        return HttpResponse("You need to pass a url to ?redirect=", status=400)
    if not request.headers.get("referer"):
        return HttpResponse('You need to make a request that includes the "Referer" header.', status=400)

    current_team = cast(User, request.user).team
    referer_url = urlparse(request.headers["referer"])
    redirect_url = urlparse(request.GET["redirect"])
    is_forum_login = request.GET.get("forum_login", "").lower() == "true"

    if (
        not current_team
        or (redirect_url.hostname not in PERMITTED_FORUM_DOMAINS and is_forum_login)
        or (not is_forum_login and not hostname_in_allowed_url_list(current_team.app_urls, redirect_url.hostname))
    ):
        hostname = redirect_url.hostname or request.GET["redirect"]
        return render_template(
            "toolbar_oauth_error.html",
            request,
            context={
                "error_title": "Domain not authorized",
                "error_message": "The toolbar cannot authenticate on this domain because it is not in your project's authorized URLs.",
                "error_detail": (
                    f"The hostname {hostname} needs to be added to your project's "
                    "authorized URLs before the toolbar can be used on this site."
                ),
                "error_code": "403",
                "settings_url": f"{settings.SITE_URL}/settings/project-toolbar#authorized-urls",
            },
            status_code=403,
        )

    if referer_url.hostname != redirect_url.hostname:
        return HttpResponse(
            f"Can only redirect to the same domain as the referer: {referer_url.hostname}",
            status=403,
        )

    if referer_url.scheme != redirect_url.scheme:
        return HttpResponse(
            f"Can only redirect to the same scheme as the referer: {referer_url.scheme}",
            status=403,
        )

    if referer_url.port != redirect_url.port:
        return HttpResponse(
            f"Can only redirect to the same port as the referer: {referer_url.port or 'no port in URL'}",
            status=403,
        )

    return render_template(
        "authorize_and_link.html" if is_forum_login else "authorize_and_redirect.html",
        request=request,
        context={
            "email": request.user,
            "domain": redirect_url.hostname,
            "redirect_url": request.GET["redirect"],
            "authorization_url": f"/api/user/redirect_to_site/?{urlencode({'appUrl': request.GET['redirect']})}",
        },
    )


urlpatterns = [
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # Optional UI:
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/schema/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    # Health check probe endpoints for K8s
    # NOTE: We have _health, livez, and _readyz. _health is deprecated and
    # is only included for compatability with old installations. For new
    # operations livez and readyz should be used.
    opt_slash_path("_health", health),
    opt_slash_path("_stats", stats),
    opt_slash_path("_preflight", preflight_check),
    # ee
    *ee_urlpatterns,
    # api
    # nosemgrep: no-environments-url-path -- defunct query-progress stub, pending removal
    path("api/environments/<int:team_id>/progress/", progress),
    # nosemgrep: no-environments-url-path -- defunct query-progress stub, pending removal
    path("api/environments/<int:team_id>/query/<str:query_uuid>/progress/", progress),
    # nosemgrep: no-environments-url-path -- defunct query-progress stub, pending removal
    path("api/environments/<int:team_id>/query/<str:query_uuid>/progress", progress),
    path("api/unsubscribe", unsubscribe.unsubscribe),
    path("api/alerts/github", github.SecretAlert.as_view()),
    path(
        "api/legal_documents/pandadoc",
        csrf_exempt(legal_document_pandadoc_webhook),
        name="legal_document_pandadoc_webhook",
    ),
    path(
        "api/users/<str:user_id>/signal_autonomy/",
        signals_user_autonomy_view.as_view(),
        name="user_signal_autonomy",
    ),
    # Dual-served on both prefixes while the Customer.io dispatcher is repointed from the
    # legacy /api/environments/ URL to the canonical /api/projects/ one.
    # nosemgrep: no-environments-url-path -- customerio posts to this fixed env URL; dispatcher migrating to projects
    path("api/environments/<int:team_id>/messaging/customerio/webhook/", csrf_exempt(CustomerIOWebhookView.as_view())),
    path("api/projects/<int:team_id>/messaging/customerio/webhook/", csrf_exempt(CustomerIOWebhookView.as_view())),
    path(
        "api/user_interviews/vapi_webhook/",
        csrf_exempt(vapi_webhook),
        name="user_interviews_vapi_webhook",
    ),
    path(
        "api/user_interviews/share/<str:access_token>/start_call/",
        csrf_exempt(user_interviews_start_call),
        name="user_interviews_start_call",
    ),
    path("api/sdk_health/", sdk_health),
    path("api/conversations/", include("products.conversations.backend.api.urls")),
    path("api/customer_analytics/", include("products.customer_analytics.backend.presentation.views.urls")),
    # nosemgrep: no-environments-url-path -- legacy dual-route env alias, pending env-prefix retirement
    path(
        "api/environments/<int:parent_lookup_team_id>/mcp_analytics/",
        include("products.mcp_analytics.backend.presentation.urls"),
    ),
    path(
        "api/projects/<int:parent_lookup_team_id>/mcp_analytics/",
        include("products.mcp_analytics.backend.presentation.urls"),
    ),
    # nosemgrep: no-environments-url-path -- legacy dual-route env alias, pending env-prefix retirement
    path(
        "api/environments/<int:parent_lookup_team_id>/property_access_controls/",
        include("products.access_control.backend.presentation.urls"),
    ),
    path(
        "api/projects/<int:parent_lookup_team_id>/property_access_controls/",
        include("products.access_control.backend.presentation.urls"),
    ),
    opt_slash_path("api/support/ensure-zendesk-organization", csrf_exempt(ensure_zendesk_organization)),
    path("api/", include(router.urls)),
    # Override the tf_urls QRGeneratorView to use the cache-aware version (handles session race conditions)
    path("account/two_factor/qrcode/", CacheAwareQRGeneratorView.as_view()),
    path("", include(tf_urls)),
    opt_slash_path("api/user/prepare_toolbar_preloaded_flags", user.prepare_toolbar_preloaded_flags),
    opt_slash_path("api/user/get_toolbar_preloaded_flags", user.get_toolbar_preloaded_flags),
    opt_slash_path("api/user/toolbar_oauth_refresh", user.toolbar_oauth_refresh),
    path("toolbar_oauth/authorize/", login_required(user.toolbar_oauth_authorize)),
    path("toolbar_oauth/callback", user.toolbar_oauth_callback),
    path("toolbar_oauth/check", user.toolbar_oauth_check),
    opt_slash_path("api/user/redirect_to_site", user.redirect_to_site),
    opt_slash_path("api/user/redirect_to_website", user.redirect_to_website),
    opt_slash_path("api/early_access_features", early_access_features),
    opt_slash_path("api/web_experiments", web_experiments),
    opt_slash_path("api/push_subscriptions", push_subscriptions),
    opt_slash_path("api/product_tours", product_tours),
    re_path(r"^external_surveys/(?P<survey_id>[^/]+)/?$", public_survey_page),
    opt_slash_path("api/signup/precheck", signup.SignupEmailPrecheckViewset.as_view()),
    opt_slash_path("api/signup/resend-invite", signup.SignupResendInviteViewset.as_view()),
    opt_slash_path("api/signup", signup.SignupViewset.as_view()),
    opt_slash_path("api/social_signup", signup.SocialSignupViewset.as_view()),
    path("api/signup/<str:invite_id>/", signup.InviteSignupViewset.as_view()),
    path(
        "api/reset/<str:user_uuid>/",
        authentication.PasswordResetCompleteViewSet.as_view({"get": "retrieve", "post": "create"}),
    ),
    path(
        "api/reset_2fa/<str:user_uuid>/",
        two_factor_reset.TwoFactorResetViewSet.as_view({"get": "retrieve", "post": "create"}),
    ),
    opt_slash_path(
        "api/public_hog_function_templates",
        hog_function_template.PublicHogFunctionTemplateViewSet.as_view({"get": "list"}),
    ),
    opt_slash_path(
        "api/public_hog_flow_templates",
        hog_flow_template.PublicHogFlowTemplateViewSet.as_view({"get": "list"}),
    ),
    opt_slash_path(
        "api/public_source_configs",
        PublicSourceConfigViewSet.as_view({"get": "list"}),
    ),
    # Internal agent-proxy side-effect callback (auth: sandbox event ingest JWT)
    path(
        "internal/tasks/runs/<str:run_id>/agent-proxy-callback/",
        csrf_exempt(agent_proxy_callback),
    ),
    # Internal SQLV2 run result callback (auth: signed callback token)
    path(
        "internal/notebooks/runs/<str:run_id>/result/",
        csrf_exempt(notebook_sql_v2_callback),
    ),
    # Internal SQLV2 data plane — the sandbox's HogQL read path (auth: signed data-plane token)
    path(
        "internal/notebooks/data_plane/query/",
        csrf_exempt(notebook_sql_v2_data_plane),
    ),
    # Internal service-to-service endpoints (authenticated with POSTHOG_INTERNAL_SERVICE_TOKEN)
    path(
        "api/projects/<str:team_id>/internal/hog_flows/user_blast_radius",
        csrf_exempt(hog_flow.InternalHogFlowViewSet.as_view({"post": "internal_user_blast_radius"})),
    ),
    path(
        "api/projects/<str:team_id>/internal/hog_flows/user_blast_radius_persons",
        csrf_exempt(hog_flow.InternalHogFlowViewSet.as_view({"post": "internal_user_blast_radius_persons"})),
    ),
    path(
        "api/internal/hog_flows/process_due_schedules",
        csrf_exempt(hog_flow.InternalHogFlowViewSet.as_view({"post": "internal_process_due_schedules"})),
    ),
    path(
        "api/projects/<str:team_id>/internal/hog_flows/batch_jobs/<str:batch_job_id>/status",
        csrf_exempt(hog_flow.InternalHogFlowViewSet.as_view({"put": "internal_update_batch_job_status"})),
    ),
    path(
        "api/projects/<str:team_id>/internal/signals/emit",
        csrf_exempt(signals_views.InternalSignalViewSet.as_view({"post": "emit"})),
    ),
    # Test setup endpoint (only available in TEST mode)
    path("api/setup_test/<str:test_name>/", csrf_exempt(playwright_setup.setup_test)),
    opt_slash_path(
        "api/oauth/connected-apps",
        ConnectedAppsViewSet.as_view({"get": "list"}),
    ),
    path(
        "api/oauth/connected-apps/<uuid:pk>/revoke/",
        ConnectedAppsViewSet.as_view({"post": "revoke"}),
    ),
    path(
        WIZARD_METADATA_PATH,
        WizardClientMetadataView.as_view(),
        name="wizard-client-metadata",
    ),
    path(
        RAYCAST_METADATA_PATH,
        RaycastClientMetadataView.as_view(),
        name="raycast-client-metadata",
    ),
    re_path(r"^api.+", api_not_found),
    path("authorize_and_redirect/", login_required(authorize_and_redirect)),
    path("integrations/connect/<str:kind>/", login_required(integration_connect_redirect)),
    path(
        "shared_dashboard/<str:access_token>",
        sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"}),
    ),
    path(
        "shared/<str:access_token>",
        sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"}),
    ),
    path(
        "embedded/<str:access_token>",
        sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"}),
    ),
    path(
        "interview/<str:access_token>",
        sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"}),
    ),
    path("render_query", render_query, name="render_query"),
    path("exporter", sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"})),
    path(
        "exporter/<str:access_token>",
        sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"}),
    ),
    path("site_app/<int:id>/<str:token>/<str:hash>/", site_app.get_site_app),
    re_path(r"^demo.*", login_required(demo_route)),
    path("", include((oauth2_urls, "oauth2_provider"), namespace="oauth2_provider")),
    # ingestion
    # NOTE: When adding paths here that should be public make sure to update ALWAYS_ALLOWED_ENDPOINTS in middleware.py
    opt_slash_path("report", report.get_csp_event),  # CSP violation reports
    opt_slash_path("robots.txt", robots_txt),
    opt_slash_path(".well-known/security.txt", security_txt),
    # auth
    opt_slash_path("logout", authentication.logout, name="logout"),
    path(
        "login/<str:backend>/", authentication.sso_login, name="social_begin"
    ),  # overrides from `social_django.urls` to validate proper license
    # GitHub account linking (identity-only, separate from the login pipeline).
    # Must precede `social_django.urls` so the latter's `complete/<str:backend>/` doesn't swallow it.
    path("complete/github-link/", github_oauth_callback, name="github_link_complete"),
    opt_slash_path(
        "integrations/github/callback", github_setup_callback, name="github_team_integration_setup_callback"
    ),
    # Slack user-identity linking — mirrors the GitHub per-user pattern above,
    # and likewise must precede `social_django.urls` for the same reason.
    path("complete/slack-link/start/", slack_user_link_authorize, name="slack_link_start"),
    path("complete/slack-link/", slack_user_link_callback, name="slack_link_complete"),
    path("", include("social_django.urls", namespace="social")),
    path("uploaded_media/<str:image_uuid>", uploaded_media.download),
    opt_slash_path("slack/interactivity-callback", posthog_code_interactivity_handler),
    opt_slash_path("slack/event-callback", posthog_code_event_handler),
    opt_slash_path("slack/command-callback", slack_app_command_handler),
    opt_slash_path("slack/workspace/claims", slack_workspace_claims_view),
    # GitHub App webhook — fans out to tasks (PRs) and conversations (issues)
    opt_slash_path("webhooks/github/pr", github_webhook),
    opt_slash_path("webhooks/github", github_webhook),
    # Message preferences
    path("messaging-preferences/<str:token>/", preferences_page, name="message_preferences"),
    opt_slash_path("messaging-preferences/update", update_preferences, name="message_preferences_update"),
]

# Personal LLM spend data only lives in PostHog Cloud US — EU forwards its product
# LLM telemetry over, so EU callers get a 302 to the US-hosted endpoint instead of
# a silent 404. Must be inserted *before* the `^api.+` catch-all above; otherwise
# the catch-all matches first and the redirect is unreachable.
if settings.CLOUD_DEPLOYMENT == "EU":
    urlpatterns.insert(
        0,
        path(
            "api/llm_analytics/@me/spend/",
            personal_spend_eu_redirect,
            name="personal_spend_eu_redirect",
        ),
    )

if settings.DEBUG:
    # If we have DEBUG=1 set, then let's expose the metrics for debugging. Note
    # that in production we expose these metrics on a separate port (8001), to ensure
    # external clients cannot see them. See bin/granian_metrics.py and bin/unit_metrics.py
    # for details on the production metrics setup.

    # Use multiprocess mode to collect metrics from all processes (Django + Celery workers)
    import os

    def metrics_view(request):
        """Metrics endpoint that aggregates from all processes using multiprocess mode."""
        registry = CollectorRegistry()
        # If prometheus_multiproc_dir is set, collect from all processes
        if "prometheus_multiproc_dir" in os.environ or "PROMETHEUS_MULTIPROC_DIR" in os.environ:
            multiprocess.MultiProcessCollector(registry)
        else:
            # Fallback to default registry if multiprocess not configured
            from prometheus_client import REGISTRY

            registry = REGISTRY

        metrics_output = generate_latest(registry)
        return HttpResponse(metrics_output, content_type="text/plain; charset=utf-8; version=0.0.4")

    urlpatterns.append(path("_metrics", metrics_view))
    # Temporal codec server endpoint for UI decryption - locally only for now
    urlpatterns.append(path("decode", decode_payloads, name="temporal_decode"))


if settings.TEST:
    # Used in posthog-js e2e tests
    @csrf_exempt
    def delete_events(request):
        from posthog.clickhouse.client import sync_execute
        from posthog.models.event.sql import TRUNCATE_EVENTS_TABLE_SQL

        sync_execute(TRUNCATE_EVENTS_TABLE_SQL())
        return HttpResponse()

    urlpatterns.append(path("delete_events/", delete_events))
    # Temporal codec server endpoint for UI decryption - needed for tests (if not added already in DEBUG)
    if not settings.DEBUG:
        urlpatterns.append(path("decode", decode_payloads, name="temporal_decode"))


# Redirect the legacy `/sign-up` path to the canonical `/signup` route. Works across
# app./us./eu. subdomains because only the path changes; the host is preserved by the
# relative redirect.
urlpatterns.append(
    opt_slash_path("sign-up", RedirectView.as_view(url="/signup", permanent=True, query_string=True)),
)

# Routes added individually to remove login requirement
frontend_unauthenticated_routes = [
    "preflight",
    "signup",
    r"signup\/[A-Za-z0-9\-]*",
    "reset",
    "organization/billing/subscribed",
    "organization/confirm-creation",
    "login",
    "unsubscribe",
    # Public bridge for desktop-app canvas share links — deep-links into PostHog Code.
    r"code/canvas/[^/]+/[^/]+",
    "verify_email",
    r"agentic/account-mismatch",
    # OAuth redirect target when logging the local frontend into a remote cloud region;
    # the SPA handles the code→token exchange client-side, so it must load without auth.
    r"^oauth/callback",
]
for route in frontend_unauthenticated_routes:
    urlpatterns.append(re_path(route, home))

urlpatterns.append(re_path(r"^.*", home_with_region_redirect))
