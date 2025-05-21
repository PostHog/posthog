from collections.abc import Callable
from typing import Any, Optional, cast
from urllib.parse import urlparse

import structlog
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, HttpResponseServerError
from django.template import loader
from django.urls import URLPattern, include, path, re_path
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import (
    csrf_exempt,
    ensure_csrf_cookie,
    requires_csrf_token,
)
from django_prometheus.exports import ExportToDjangoView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from sentry_sdk import last_event_id
from two_factor.urls import urlpatterns as tf_urls

from posthog.api import (
    api_not_found,
    authentication,
    capture,
    decide,
    hog_function_template,
    remote_config,
    router,
    sharing,
    signup,
    site_app,
    unsubscribe,
    uploaded_media,
    user,
)
from .api.web_experiment import web_experiments
from .api.utils import hostname_in_allowed_url_list
from products.early_access_features.backend.api import early_access_features
from products.chat.backend.api import chat_endpoints
from posthog.api.survey import surveys
from posthog.constants import PERMITTED_FORUM_DOMAINS
from posthog.demo.legacy import demo_route
from posthog.models import User
from posthog.models.instance_setting import get_instance_setting

from .utils import render_template
from .views import (
    health,
    login_required,
    preflight_check,
    redis_values_view,
    robots_txt,
    security_txt,
    stats,
)
from posthog.api.query import progress

from posthog.api.slack import slack_interactivity_callback

logger = structlog.get_logger(__name__)

ee_urlpatterns: list[Any] = []
try:
    from ee.urls import extend_api_router
    from ee.urls import urlpatterns as ee_urlpatterns
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
    Context: None
    """
    template = loader.get_template("500.html")
    return HttpResponseServerError(template.render({"sentry_event_id": last_event_id()}))


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


def opt_slash_path(route: str, view: Callable, name: Optional[str] = None) -> URLPattern:
    """Catches path with or without trailing slash, taking into account query param and hash."""
    # Ignoring the type because while name can be optional on re_path, mypy doesn't agree
    return re_path(rf"^{route}/?(?:[?#].*)?$", view, name=name)  # type: ignore


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
    re_path(r"^admin/redisvalues$", redis_values_view, name="redis_values"),
    # ee
    *ee_urlpatterns,
    # api
    path("api/environments/<int:team_id>/progress/", progress),
    path("api/environments/<int:team_id>/query/<str:query_uuid>/progress/", progress),
    path("api/environments/<int:team_id>/query/<str:query_uuid>/progress", progress),
    path("api/unsubscribe", unsubscribe.unsubscribe),
    path("api/", include(router.urls)),
    path("", include(tf_urls)),
    opt_slash_path("api/user/redirect_to_site", user.redirect_to_site),
    opt_slash_path("api/user/redirect_to_website", user.redirect_to_website),
    opt_slash_path("api/user/test_slack_webhook", user.test_slack_webhook),
    opt_slash_path("api/early_access_features", early_access_features),
    opt_slash_path("api/web_experiments", web_experiments),
    opt_slash_path("api/surveys", surveys),
    opt_slash_path("api/chat", chat_endpoints),
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
    # ingestion
    # NOTE: When adding paths here that should be public make sure to update ALWAYS_ALLOWED_ENDPOINTS in middleware.py
    opt_slash_path("decide", decide.get_decide),
    opt_slash_path("e", capture.get_event),
    opt_slash_path("engage", capture.get_event),
    opt_slash_path("track", capture.get_event),
    opt_slash_path("capture", capture.get_event),
    opt_slash_path("batch", capture.get_event),
    opt_slash_path("s", capture.get_event),  # session recordings
    opt_slash_path("report", capture.get_csp_event),  # CSP violation reports
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
]

if settings.DEBUG:
    # If we have DEBUG=1 set, then let's expose the metrics for debugging. Note
    # that in production we expose these metrics on a separate port, to ensure
    # external clients cannot see them. See the gunicorn setup for details on
    # what we do.
    urlpatterns.append(path("_metrics", ExportToDjangoView))


if settings.TEST:
    # Used in posthog-js e2e tests
    @csrf_exempt
    def delete_events(request):
        from posthog.clickhouse.client import sync_execute
        from posthog.models.event.sql import TRUNCATE_EVENTS_TABLE_SQL

        sync_execute(TRUNCATE_EVENTS_TABLE_SQL())
        return HttpResponse()

    urlpatterns.append(path("delete_events/", delete_events))


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
