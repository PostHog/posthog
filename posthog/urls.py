from typing import Any, Callable, List, Optional, cast
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseServerError
from django.template import loader
from django.urls import URLPattern, include, path, re_path
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
from revproxy.views import ProxyView
from sentry_sdk import last_event_id
from two_factor.urls import urlpatterns as tf_urls

from posthog.api import (
    api_not_found,
    authentication,
    capture,
    decide,
    organizations_router,
    project_dashboards_router,
    project_feature_flags_router,
    projects_router,
    router,
    sharing,
    signup,
    site_app,
    unsubscribe,
    uploaded_media,
    user,
)
from posthog.api.decide import hostname_in_allowed_url_list
from posthog.api.early_access_feature import early_access_features
from posthog.api.prompt import prompt_webhook
from posthog.api.survey import surveys
from posthog.demo.legacy import demo_route
from posthog.models import User
from .utils import render_template
from .views import (
    health,
    login_required,
    preflight_check,
    robots_txt,
    security_txt,
    stats,
)
from .year_in_posthog import year_in_posthog

ee_urlpatterns: List[Any] = []
try:
    from ee.urls import extend_api_router
    from ee.urls import urlpatterns as ee_urlpatterns
except ImportError:
    pass
else:
    extend_api_router(
        router,
        projects_router=projects_router,
        organizations_router=organizations_router,
        project_dashboards_router=project_dashboards_router,
        project_feature_flags_router=project_feature_flags_router,
    )


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
    return render_template("index.html", request)


def authorize_and_redirect(request: HttpRequest) -> HttpResponse:
    if not request.GET.get("redirect"):
        return HttpResponse("You need to pass a url to ?redirect=", status=400)
    if not request.META.get("HTTP_REFERER"):
        return HttpResponse('You need to make a request that includes the "Referer" header.', status=400)

    current_team = cast(User, request.user).team
    referer_url = urlparse(request.META["HTTP_REFERER"])
    redirect_url = urlparse(request.GET["redirect"])

    if not current_team or not hostname_in_allowed_url_list(current_team.app_urls, redirect_url.hostname):
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
        "authorize_and_redirect.html",
        request=request,
        context={
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
    # ee
    *ee_urlpatterns,
    # api
    path("api/unsubscribe", unsubscribe.unsubscribe),
    path("api/", include(router.urls)),
    path("", include(tf_urls)),
    opt_slash_path("api/user/redirect_to_site", user.redirect_to_site),
    opt_slash_path("api/user/test_slack_webhook", user.test_slack_webhook),
    opt_slash_path("api/prompts/webhook", prompt_webhook),
    opt_slash_path("api/early_access_features", early_access_features),
    opt_slash_path("api/surveys", surveys),
    opt_slash_path("api/signup", signup.SignupViewset.as_view()),
    opt_slash_path("api/social_signup", signup.SocialSignupViewset.as_view()),
    path("api/signup/<str:invite_id>/", signup.InviteSignupViewset.as_view()),
    path(
        "api/reset/<str:user_uuid>/",
        authentication.PasswordResetCompleteViewSet.as_view({"get": "retrieve", "post": "create"}),
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
    opt_slash_path("robots.txt", robots_txt),
    opt_slash_path(".well-known/security.txt", security_txt),
    # auth
    path("logout", authentication.logout, name="login"),
    path(
        "login/<str:backend>/", authentication.sso_login, name="social_begin"
    ),  # overrides from `social_django.urls` to validate proper license
    path("", include("social_django.urls", namespace="social")),
    path("uploaded_media/<str:image_uuid>", uploaded_media.download),
    path("year_in_posthog/2022/<str:user_uuid>", year_in_posthog.render_2022),
    path("year_in_posthog/2022/<str:user_uuid>/", year_in_posthog.render_2022),
]

if settings.DEBUG:
    # If we have DEBUG=1 set, then let's expose the metrics for debugging. Note
    # that in production we expose these metrics on a separate port, to ensure
    # external clients cannot see them. See the gunicorn setup for details on
    # what we do.
    urlpatterns.append(path("_metrics", ExportToDjangoView))

    # Reverse-proxy all of /i/* to capture-rs on port 3000 when running the local devenv
    urlpatterns.append(re_path(r"(?P<path>^i/.*)", ProxyView.as_view(upstream="http://localhost:3000")))


if settings.TEST:
    # Used in posthog-js e2e tests
    @csrf_exempt
    def delete_events(request):
        from posthog.client import sync_execute
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
