from typing import Any, cast
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, HttpResponseServerError
from django.template import loader
from django.urls import include, path, re_path
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie, requires_csrf_token

import structlog
from django_prometheus.exports import ExportToDjangoView
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from two_factor.urls import urlpatterns as tf_urls

from posthog.api import (
    api_not_found,
    authentication,
    decide,
    github,
    hog_function_template,
    playwright_setup,
    remote_config,
    report,
    router,
    sharing,
    signup,
    site_app,
    unsubscribe,
    uploaded_media,
    user,
)
from posthog.api.github_sdk_versions import github_sdk_versions
from posthog.api.query import progress
from posthog.api.slack import slack_interactivity_callback
from posthog.api.survey import public_survey_page, surveys
from posthog.api.team_sdk_versions import team_sdk_versions
from posthog.api.two_factor_qrcode import CacheAwareQRGeneratorView
from posthog.api.utils import hostname_in_allowed_url_list
from posthog.api.web_experiment import web_experiments
from posthog.api.zendesk_orgcheck import ensure_zendesk_organization
from posthog.constants import PERMITTED_FORUM_DOMAINS
from posthog.demo.legacy import demo_route
from posthog.models import User
from posthog.models.instance_setting import get_instance_setting
from posthog.oauth2_urls import urlpatterns as oauth2_urls
from posthog.temporal.codec_server import decode_payloads

from products.early_access_features.backend.api import early_access_features

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


@requires_csrf_token
def handler500(request):
    """
    500 error handler.

    Templates: :template:`500.html`
    Context: request
    """
    template = loader.get_template("500.html")
    return HttpResponseServerError(template.render({"request": request}, request))


@ensure_csrf_cookie
def home(request, *args, **kwargs):
    if request.get_host().split(":")[0] == "app.posthog.com" and get_instance_setting("REDIRECT_APP_TO_US"):
        url = "https://us.posthog.com{}".format(request.get_full_path())
        if url_has_allowed_host_and_scheme(url, "us.posthog.com", True):
            return HttpResponseRedirect(url)
    return render_template("index.html", request)


def authorize_and_redirect(request: HttpRequest) -> HttpResponse:
    if not request.GET.get("redirect"):
        return HttpResponse("You need to pass a url to ?redirect=", status=400)
    if not request.META.get("HTTP_REFERER"):
        return HttpResponse('You need to make a request that includes the "Referer" header.', status=400)

    current_team = cast(User, request.user).team
    referer_url = urlparse(request.META["HTTP_REFERER"])
    redirect_url = urlparse(request.GET["redirect"])
    is_forum_login = request.GET.get("forum_login", "").lower() == "true"

    if (
        not current_team
        or (redirect_url.hostname not in PERMITTED_FORUM_DOMAINS and is_forum_login)
        or (not is_forum_login and not hostname_in_allowed_url_list(current_team.app_urls, redirect_url.hostname))
    ):
        return HttpResponse(f"Can only redirect to a permitted domain.", status=403)

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
    path("api/environments/<int:team_id>/progress/", progress),
    path("api/environments/<int:team_id>/query/<str:query_uuid>/progress/", progress),
    path("api/environments/<int:team_id>/query/<str:query_uuid>/progress", progress),
    path("api/unsubscribe", unsubscribe.unsubscribe),
    path("api/alerts/github", github.SecretAlert.as_view()),
    path("api/sdk_versions/", github_sdk_versions),
    path("api/team_sdk_versions/", team_sdk_versions),
    opt_slash_path("api/support/ensure-zendesk-organization", csrf_exempt(ensure_zendesk_organization)),
    path("api/", include(router.urls)),
    # Override the tf_urls QRGeneratorView to use the cache-aware version (handles session race conditions)
    path("account/two_factor/qrcode/", CacheAwareQRGeneratorView.as_view()),
    path("", include(tf_urls)),
    opt_slash_path("api/user/redirect_to_site", user.redirect_to_site),
    opt_slash_path("api/user/redirect_to_website", user.redirect_to_website),
    opt_slash_path("api/user/test_slack_webhook", user.test_slack_webhook),
    opt_slash_path("api/early_access_features", early_access_features),
    opt_slash_path("api/web_experiments", web_experiments),
    opt_slash_path("api/surveys", surveys),
    re_path(r"^external_surveys/(?P<survey_id>[^/]+)/?$", public_survey_page),
    opt_slash_path("api/signup", signup.SignupViewset.as_view()),
    opt_slash_path("api/social_signup", signup.SocialSignupViewset.as_view()),
    path("api/signup/<str:invite_id>/", signup.InviteSignupViewset.as_view()),
    path(
        "api/reset/<str:user_uuid>/",
        authentication.PasswordResetCompleteViewSet.as_view({"get": "retrieve", "post": "create"}),
    ),
    opt_slash_path(
        "api/public_hog_function_templates",
        hog_function_template.PublicHogFunctionTemplateViewSet.as_view({"get": "list"}),
    ),
    # Test setup endpoint (only available in TEST mode)
    path("api/setup_test/<str:test_name>/", csrf_exempt(playwright_setup.setup_test)),
    re_path(r"^api.+", api_not_found),
    path("authorize_and_redirect/", login_required(authorize_and_redirect)),
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
    path("render_query", render_query, name="render_query"),
    path("exporter", sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"})),
    path(
        "exporter/<str:access_token>",
        sharing.SharingViewerPageViewSet.as_view({"get": "retrieve"}),
    ),
    path("site_app/<int:id>/<str:token>/<str:hash>/", site_app.get_site_app),
    path("array/<str:token>/config", remote_config.RemoteConfigAPIView.as_view()),
    path("array/<str:token>/config.js", remote_config.RemoteConfigJSAPIView.as_view()),
    path("array/<str:token>/array.js", remote_config.RemoteConfigArrayJSAPIView.as_view()),
    re_path(r"^demo.*", login_required(demo_route)),
    path("", include((oauth2_urls, "oauth2_provider"), namespace="oauth2_provider")),
    # ingestion
    # NOTE: When adding paths here that should be public make sure to update ALWAYS_ALLOWED_ENDPOINTS in middleware.py
    opt_slash_path("decide", decide.get_decide),
    opt_slash_path("report", report.get_csp_event),  # CSP violation reports
    opt_slash_path("robots.txt", robots_txt),
    opt_slash_path(".well-known/security.txt", security_txt),
    # auth
    path("logout", authentication.logout, name="login"),
    path(
        "login/<str:backend>/", authentication.sso_login, name="social_begin"
    ),  # overrides from `social_django.urls` to validate proper license
    path("", include("social_django.urls", namespace="social")),
    path("uploaded_media/<str:image_uuid>", uploaded_media.download),
    opt_slash_path("slack/interactivity-callback", slack_interactivity_callback),
    # Message preferences
    path("messaging-preferences/<str:token>/", preferences_page, name="message_preferences"),
    opt_slash_path("messaging-preferences/update", update_preferences, name="message_preferences_update"),
]

if settings.DEBUG:
    # If we have DEBUG=1 set, then let's expose the metrics for debugging. Note
    # that in production we expose these metrics on a separate port (8001), to ensure
    # external clients cannot see them. See bin/granian_metrics.py and bin/unit_metrics.py
    # for details on the production metrics setup.
    urlpatterns.append(path("_metrics", ExportToDjangoView))
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
    "verify_email",
]
for route in frontend_unauthenticated_routes:
    urlpatterns.append(re_path(route, home))

urlpatterns.append(re_path(r"^.*", login_required(home)))
