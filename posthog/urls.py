from typing import Any, Callable, List, Optional
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import URLPattern, include, path, re_path
from django.urls.base import reverse
from django.views.decorators import csrf
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from posthog.api import (
    api_not_found,
    authentication,
    capture,
    dashboard,
    decide,
    project_dashboards_router,
    projects_router,
    router,
    signup,
    user,
)
from posthog.demo import demo

from .utils import render_template
from .views import health, login_required, preflight_check, robots_txt, stats

ee_urlpatterns: List[Any] = []
try:
    from ee.urls import extend_api_router
    from ee.urls import urlpatterns as ee_urlpatterns
except ImportError:
    pass
else:
    extend_api_router(router, projects_router=projects_router, project_dashboards_router=project_dashboards_router)


@csrf.ensure_csrf_cookie
def home(request, *args, **kwargs):
    return render_template("index.html", request)


def login_view(request):
    """
    Checks if SAML is enforced and prevents using password authentication if it's the case.
    """
    if getattr(settings, "SAML_ENFORCED", False):
        return redirect(f'{reverse("social:begin", kwargs={"backend": "saml"})}?idp=posthog_custom')
    return home(request)


def authorize_and_redirect(request):
    if not request.GET.get("redirect"):
        return HttpResponse("You need to pass a url to ?redirect=", status=401)
    url = request.GET["redirect"]
    return render_template(
        "authorize_and_redirect.html",
        request=request,
        context={"domain": urlparse(url).hostname, "redirect_url": url,},
    )


def opt_slash_path(route: str, view: Callable, name: Optional[str] = None) -> URLPattern:
    """Catches path with or without trailing slash, taking into account query param and hash."""
    # Ignoring the type because while name can be optional on re_path, mypy doesn't agree
    return re_path(fr"^{route}/?(?:[?#].*)?$", view, name=name)  # type: ignore


urlpatterns = [
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    # Optional UI:
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
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
    path("api/", include(router.urls)),
    opt_slash_path("api/user/redirect_to_site", user.redirect_to_site),
    opt_slash_path("api/user/test_slack_webhook", user.test_slack_webhook),
    opt_slash_path("api/signup", signup.SignupViewset.as_view()),
    opt_slash_path("api/social_signup", signup.SocialSignupViewset.as_view()),
    path("api/signup/<str:invite_id>/", signup.InviteSignupViewset.as_view()),
    path(
        "api/reset/<str:user_uuid>/",
        authentication.PasswordResetCompleteViewSet.as_view({"get": "retrieve", "post": "create"}),
    ),
    re_path(r"^api.+", api_not_found),
    path("authorize_and_redirect/", login_required(authorize_and_redirect)),
    path("shared_dashboard/<str:share_token>", dashboard.shared_dashboard),
    re_path(r"^demo.*", login_required(demo)),
    # ingestion
    opt_slash_path("decide", decide.get_decide),
    opt_slash_path("e", capture.get_event),
    opt_slash_path("engage", capture.get_event),
    opt_slash_path("track", capture.get_event),
    opt_slash_path("capture", capture.get_event),
    opt_slash_path("batch", capture.get_event),
    opt_slash_path("s", capture.get_event),  # session recordings
    opt_slash_path("robots.txt", robots_txt),
    # auth
    path("logout", authentication.logout, name="login"),
    path("signup/finish/", signup.finish_social_signup, name="signup_finish"),
    path("", include("social_django.urls", namespace="social")),
    path("login", login_view),
]

if settings.TEST:

    # Used in posthog-js e2e tests
    @csrf_exempt
    def delete_events(request):
        from ee.clickhouse.client import sync_execute
        from ee.clickhouse.sql.events import TRUNCATE_EVENTS_TABLE_SQL

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
]
for route in frontend_unauthenticated_routes:
    urlpatterns.append(re_path(route, home))

urlpatterns.append(re_path(r"^.*", login_required(home)))
