import uuid
from contextlib import suppress
from datetime import datetime, timedelta
from posthog.geoip import get_geoip_properties
import time
from ipaddress import ip_address, ip_network
from typing import Optional, cast
from collections.abc import Callable
from loginas.utils import is_impersonated_session, restore_original_login
from posthog.rbac.user_access_control import UserAccessControl
from django.shortcuts import redirect
import structlog
from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import MiddlewareNotUsed
from django.db import connection
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.urls import resolve
from django.utils.cache import add_never_cache_headers
from django_prometheus.middleware import (
    Metrics,
)
from rest_framework import status
from statshog.defaults.django import statsd
from django.core.cache import cache

from posthog.api.decide import get_decide
from posthog.api.shared import UserBasicSerializer
from posthog.clickhouse.client.execute import clickhouse_query_counter
from posthog.clickhouse.query_tagging import QueryCounter, reset_query_tags, tag_queries
from posthog.cloud_utils import is_cloud
from posthog.exceptions import generate_exception_response
from posthog.models import Action, Cohort, Dashboard, FeatureFlag, Insight, Notebook, User, Team
from posthog.rate_limit import DecideRateThrottle
from posthog.settings import SITE_URL, PROJECT_SWITCHING_TOKEN_ALLOWLIST
from posthog.user_permissions import UserPermissions
from posthog.models.utils import generate_random_token
from .auth import PersonalAPIKeyAuthentication
from .utils_cors import cors_response

ALWAYS_ALLOWED_ENDPOINTS = [
    "decide",
    "static",
    "_health",
    "flags",
    "messaging-preferences",
    "i",
]

default_cookie_options = {
    "max_age": 365 * 24 * 60 * 60,  # one year
    "expires": None,
    "path": "/",
    "domain": "posthog.com",
    "secure": True,
    "samesite": "Strict",
}

cookie_api_paths_to_ignore = {"decide", "api", "flags"}


class AllowIPMiddleware:
    trusted_proxies: list[str] = []

    def __init__(self, get_response):
        if not settings.ALLOWED_IP_BLOCKS and not settings.BLOCKED_GEOIP_REGIONS:
            # this will make Django skip this middleware for all future requests
            raise MiddlewareNotUsed()
        self.ip_blocks = settings.ALLOWED_IP_BLOCKS

        if settings.TRUSTED_PROXIES:
            self.trusted_proxies = [item.strip() for item in settings.TRUSTED_PROXIES.split(",")]
        self.get_response = get_response

    def get_forwarded_for(self, request: HttpRequest):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for is not None:
            return [ip.strip() for ip in forwarded_for.split(",") if ip.strip()]
        else:
            return []

    def extract_client_ip(self, request: HttpRequest):
        client_ip = request.META["REMOTE_ADDR"]
        if getattr(settings, "USE_X_FORWARDED_HOST", False):
            forwarded_for = self.get_forwarded_for(request)
            if forwarded_for:
                closest_proxy = client_ip
                client_ip = forwarded_for.pop(0)
                if settings.TRUST_ALL_PROXIES:
                    return client_ip
                proxies = [closest_proxy, *forwarded_for]
                for proxy in proxies:
                    if proxy not in self.trusted_proxies:
                        return None
        return client_ip

    def __call__(self, request: HttpRequest):
        response: HttpResponse = self.get_response(request)
        if request.path.split("/")[1] in ALWAYS_ALLOWED_ENDPOINTS:
            return response
        ip = self.extract_client_ip(request)
        if ip:
            if settings.ALLOWED_IP_BLOCKS:
                if any(ip_address(ip) in ip_network(block, strict=False) for block in self.ip_blocks):
                    return response
            elif settings.BLOCKED_GEOIP_REGIONS:
                if get_geoip_properties(ip).get("$geoip_country_code", None) not in settings.BLOCKED_GEOIP_REGIONS:
                    return response
        return HttpResponse(
            "PostHog is not available in your region. If you think this is in error, please contact tim@posthog.com.",
            status=403,
        )


class CsrfOrKeyViewMiddleware(CsrfViewMiddleware):
    """Middleware accepting requests that either contain a valid CSRF token or a personal API key."""

    def process_view(self, request, callback, callback_args, callback_kwargs):
        result = super().process_view(request, callback, callback_args, callback_kwargs)  # None if request accepted
        # if super().process_view did not find a valid CSRF token, try looking for a personal API key
        if result is not None and PersonalAPIKeyAuthentication.find_key_with_source(request) is not None:
            return self._accept(request)
        return result

    def _accept(self, request):
        request.csrf_processing_done = True
        return None


# Work around cloudflare by default caching csv files
class CsvNeverCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.endswith("csv"):
            add_never_cache_headers(response)
        return response


class AutoProjectMiddleware:
    """Automatic switching of the user's current project to that of the item being accessed if possible.

    Sometimes you get sent a link to PostHog that points to an item from a different project than the one you currently
    are in. With this middleware, if you have access to the target project, you are seamlessly switched to it,
    instead of seeing a 404 eror.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.token_allowlist = PROJECT_SWITCHING_TOKEN_ALLOWLIST

    def __call__(self, request: HttpRequest):
        if request.user.is_authenticated:
            path_parts = request.path.strip("/").split("/")
            project_id_in_url = None
            user = cast(User, request.user)

            if (
                len(path_parts) >= 2
                and path_parts[0] == "project"
                and (path_parts[1].startswith("phc_") or path_parts[1] in self.token_allowlist)
            ):

                def do_redirect():
                    new_path = "/".join(path_parts)
                    search_params = request.GET.urlencode()

                    return redirect(f"/{new_path}?{search_params}" if search_params else f"/{new_path}")

                try:
                    new_team = Team.objects.get(api_token=path_parts[1])

                    if not self.can_switch_to_team(new_team, request):
                        raise Team.DoesNotExist

                    path_parts[1] = str(new_team.pk)
                    return do_redirect()

                except Team.DoesNotExist:
                    if user.team:
                        path_parts[1] = str(user.team.pk)
                        return do_redirect()

            if len(path_parts) >= 2 and path_parts[0] == "project" and path_parts[1].isdigit():
                project_id_in_url = int(path_parts[1])

            elif (
                len(path_parts) >= 3
                and path_parts[0] == "api"
                and path_parts[1] == "project"
                and path_parts[2].isdigit()
            ):
                project_id_in_url = int(path_parts[2])

            if project_id_in_url and user.team and user.team.pk != project_id_in_url:
                try:
                    new_team = Team.objects.get(pk=project_id_in_url)
                    self.switch_team_if_allowed(new_team, request)
                except Team.DoesNotExist:
                    pass
                return self.get_response(request)

            target_queryset = self.get_target_queryset(request)
            if target_queryset is not None:
                self.switch_team_if_needed_and_allowed(request, target_queryset)
        return self.get_response(request)

    def get_target_queryset(self, request: HttpRequest) -> Optional[QuerySet]:
        # TODO: Remove this method, as all relevant links now have `project_id_in_url``

        path_parts = request.path.strip("/").split("/")
        # Sync the paths with urls.ts!
        if len(path_parts) >= 2:
            if path_parts[0] == "dashboard":
                dashboard_id = path_parts[1]
                if dashboard_id.isnumeric():
                    return Dashboard.objects.filter(deleted=False, id=dashboard_id)
            elif path_parts[0] == "insights":
                insight_short_id = path_parts[1]
                return Insight.objects.filter(deleted=False, short_id=insight_short_id)
            elif path_parts[0] == "notebooks":
                notebook_short_id = path_parts[1]
                return Notebook.objects.filter(deleted=False, short_id=notebook_short_id)
            elif path_parts[0] == "feature_flags":
                feature_flag_id = path_parts[1]
                if feature_flag_id.isnumeric():
                    return FeatureFlag.objects.filter(deleted=False, id=feature_flag_id)
            elif path_parts[0] == "action":
                action_id = path_parts[1]
                if action_id.isnumeric():
                    return Action.objects.filter(deleted=False, id=action_id)
            elif path_parts[0] == "cohorts":
                cohort_id = path_parts[1]
                if cohort_id.isnumeric():
                    return Cohort.objects.filter(deleted=False, id=cohort_id)
        return None

    def switch_team_if_needed_and_allowed(self, request: HttpRequest, target_queryset: QuerySet):
        user = cast(User, request.user)
        current_team = user.team
        if current_team is not None and not target_queryset.filter(team=current_team).exists():
            actual_item = target_queryset.only("team").select_related("team").first()
            if actual_item is not None:
                self.switch_team_if_allowed(actual_item.team, request)

    def switch_team_if_allowed(self, new_team: Team, request: HttpRequest):
        user = cast(User, request.user)

        if not self.can_switch_to_team(new_team, request):
            return

        old_team_id = user.current_team_id
        user.team = new_team
        user.current_team = new_team
        user.current_organization_id = new_team.organization_id
        user.save()
        # Information for POSTHOG_APP_CONTEXT
        request.switched_team = old_team_id  # type: ignore

    def can_switch_to_team(self, new_team: Team, request: HttpRequest):
        user = cast(User, request.user)
        user_permissions = UserPermissions(user)
        user_access_control = UserAccessControl(user=user, team=new_team)

        # :KLUDGE: This is more inefficient than needed, doing several expensive lookups
        #   However this should be a rare operation!
        if (
            not user_access_control.check_access_level_for_object(new_team, "member")
            and user_permissions.team(new_team).effective_membership_level is None
        ):
            if user.is_staff:
                # Staff users get a popup with suggested users to log in as, facilating support
                request.suggested_users_with_access = UserBasicSerializer(  # type: ignore
                    new_team.all_users_with_access().order_by("first_name", "last_name", "id"), many=True
                ).data
            return False

        return True


class CHQueries:
    def __init__(self, get_response):
        self.get_response = get_response
        self.logger = structlog.get_logger(__name__)

    def __call__(self, request: HttpRequest):
        """Install monkey-patch on demand.
        If monkey-patch has not been run in for this process (assuming multiple preforked processes),
        then do it now.
        """
        route = resolve(request.path)
        route_id = f"{route.route} ({route.func.__name__})"

        user = cast(User, request.user)

        with suppress(Exception):
            if request_id := structlog.get_context(self.logger).get("request_id"):
                tag_queries(http_request_id=uuid.UUID(request_id))

        tag_queries(
            user_id=user.pk,
            kind="request",
            id=request.path,
            route_id=route.route,
            client_query_id=self._get_param(request, "client_query_id"),
            session_id=self._get_param(request, "session_id"),
            http_referer=request.META.get("HTTP_REFERER"),
            http_user_agent=request.META.get("HTTP_USER_AGENT"),
        )

        try:
            response: HttpResponse = self.get_response(request)

            if "api/" in request.path and "capture" not in request.path:
                statsd.incr(
                    "http_api_request_response",
                    tags={"id": route_id, "status_code": response.status_code},
                )

            return response
        finally:
            reset_query_tags()

    def _get_param(self, request: HttpRequest, name: str):
        if name in request.GET:
            return request.GET[name]
        if name in request.POST:
            return request.POST[name]
        return None


class QueryTimeCountingMiddleware:
    ALLOW_LIST_ROUTES = [
        "dashboard",
        "insight",
        "property_definitions",
        "properties",
        "person",
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        if not (
            settings.CAPTURE_TIME_TO_SEE_DATA
            and "api" in request.path
            and any(key in request.path for key in self.ALLOW_LIST_ROUTES)
        ):
            return self.get_response(request)

        pg_query_counter, ch_query_counter = QueryCounter(), QueryCounter()
        start_time = time.perf_counter()
        with connection.execute_wrapper(pg_query_counter), clickhouse_query_counter(ch_query_counter):
            response: HttpResponse = self.get_response(request)

        response.headers["Server-Timing"] = self._construct_header(
            django=time.perf_counter() - start_time,
            pg=pg_query_counter.query_time_ms,
            ch=ch_query_counter.query_time_ms,
        )
        return response

    def _construct_header(self, **kwargs):
        return ", ".join(f"{key};dur={round(duration)}" for key, duration in kwargs.items())


def shortcircuitmiddleware(f):
    """view decorator, the sole purpose to is 'rename' the function
    '_shortcircuitmiddleware'"""

    def _shortcircuitmiddleware(*args, **kwargs):
        return f(*args, **kwargs)

    return _shortcircuitmiddleware


class ShortCircuitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.decide_throttler = DecideRateThrottle(
            replenish_rate=settings.DECIDE_BUCKET_REPLENISH_RATE,
            bucket_capacity=settings.DECIDE_BUCKET_CAPACITY,
        )

    def __call__(self, request: HttpRequest):
        if request.path == "/decide/" or request.path == "/decide":
            try:
                # :KLUDGE: Manually tag ClickHouse queries as CHMiddleware is skipped
                tag_queries(
                    kind="request",
                    id=request.path,
                    route_id=resolve(request.path).route,
                    http_referer=request.META.get("HTTP_REFERER"),
                    http_user_agent=request.META.get("HTTP_USER_AGENT"),
                )
                if self.decide_throttler.allow_request(request, None):
                    return get_decide(request)
                else:
                    return cors_response(
                        request,
                        generate_exception_response(
                            "decide",
                            f"Rate limit exceeded ",
                            code="rate_limit_exceeded",
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        ),
                    )
            finally:
                reset_query_tags()
        response: HttpResponse = self.get_response(request)
        return response


def per_request_logging_context_middleware(
    get_response: Callable[[HttpRequest], HttpResponse],
) -> Callable[[HttpRequest], HttpResponse]:
    """
    We get some default logging context from the django-structlog middleware,
    see
    https://django-structlog.readthedocs.io/en/latest/getting_started.html#extending-request-log-metadata
    for details. They include e.g. request_id, user_id. In some cases e.g. we
    add the team_id to the context like the get_events and decide endpoints.

    This middleware adds some additional context at the beginning of the
    request. Feel free to add anything that's relevant for the request here.
    """

    def middleware(request: HttpRequest) -> HttpResponse:
        # Add in the host header, and the x-forwarded-for header if it exists.
        # We add these such that we can see if there are any requests on cloud
        # that do not use Host header app.posthog.com. This is important as we
        # roll out CloudFront in front of app.posthog.com. We can get the host
        # header from NGINX, but we really want to have a way to get to the
        # team_id given a host header, and we can't do that with NGINX.
        structlog.contextvars.bind_contextvars(
            host=request.META.get("HTTP_HOST", ""),
            container_hostname=settings.CONTAINER_HOSTNAME,
            x_forwarded_for=request.META.get("HTTP_X_FORWARDED_FOR", ""),
        )

        return get_response(request)

    return middleware


def user_logging_context_middleware(
    get_response: Callable[[HttpRequest], HttpResponse],
) -> Callable[[HttpRequest], HttpResponse]:
    """
    This middleware adds the team_id to the logging context if it exists. Note
    that this should be added after we have performed authentication, as we
    need the user to be authenticated to get the team_id.
    """

    def middleware(request: HttpRequest) -> HttpResponse:
        if request.user.is_authenticated:
            structlog.contextvars.bind_contextvars(team_id=request.user.current_team_id)

        return get_response(request)

    return middleware


PROMETHEUS_EXTENDED_METRICS = [
    "django_http_requests_total_by_view_transport_method",
    "django_http_responses_total_by_status_view_method",
    "django_http_requests_latency_seconds_by_view_method",
]


class CustomPrometheusMetrics(Metrics):
    def register_metric(self, metric_cls, name, documentation, labelnames=(), **kwargs):
        return super().register_metric(metric_cls, name, documentation, labelnames=labelnames, **kwargs)


class PostHogTokenCookieMiddleware(SessionMiddleware):
    """
    Adds two secure cookies to enable auto-filling the current project token on the docs.
    """

    def process_response(self, request, response):
        response = super().process_response(request, response)

        if not is_cloud():
            return response

        # skip adding the cookie on API requests
        split_request_path = request.path.split("/")
        if len(split_request_path) and split_request_path[1] in cookie_api_paths_to_ignore:
            return response

        if request.path.startswith("/logout"):
            # clears the cookies that were previously set, except for ph_current_instance as that is used for the website login button
            response.delete_cookie("ph_current_project_token", domain=default_cookie_options["domain"])
            response.delete_cookie("ph_current_project_name", domain=default_cookie_options["domain"])
        if request.user and request.user.is_authenticated and request.user.team:
            response.set_cookie(
                key="ph_current_project_token",
                value=request.user.team.api_token,
                max_age=365 * 24 * 60 * 60,
                expires=default_cookie_options["expires"],
                path=default_cookie_options["path"],
                domain=default_cookie_options["domain"],
                secure=default_cookie_options["secure"],
                samesite=default_cookie_options["samesite"],
            )

            response.set_cookie(
                key="ph_current_project_name",  # clarify which project is active (orgs can have multiple projects)
                value=request.user.team.name.encode("utf-8").decode("latin-1"),
                max_age=365 * 24 * 60 * 60,
                expires=default_cookie_options["expires"],
                path=default_cookie_options["path"],
                domain=default_cookie_options["domain"],
                secure=default_cookie_options["secure"],
                samesite=default_cookie_options["samesite"],
            )

            response.set_cookie(
                key="ph_current_instance",
                value=SITE_URL,
                max_age=365 * 24 * 60 * 60,
                expires=default_cookie_options["expires"],
                path=default_cookie_options["path"],
                domain=default_cookie_options["domain"],
                secure=default_cookie_options["secure"],
                samesite=default_cookie_options["samesite"],
            )

        return response


def get_or_set_session_cookie_created_at(request: HttpRequest) -> float:
    return request.session.setdefault(settings.SESSION_COOKIE_CREATED_AT_KEY, time.time())


class SessionAgeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        # NOTE: This should be covered by the post_login signal, but we add it here as a fallback
        get_or_set_session_cookie_created_at(request=request)

        if request.user.is_authenticated:
            # Get session creation time
            session_created_at = request.session.get(settings.SESSION_COOKIE_CREATED_AT_KEY)
            if session_created_at:
                # Get timeout from Redis cache first, fallback to settings
                org_id = request.user.current_organization_id
                session_age = None
                if org_id:
                    session_age = cache.get(f"org_session_age:{org_id}")

                if session_age is None:
                    session_age = settings.SESSION_COOKIE_AGE

                current_time = time.time()
                if current_time - session_created_at > session_age:
                    # Log out the user
                    from django.contrib.auth import logout

                    logout(request)
                    return redirect("/login?message=Your session has expired. Please log in again.")

        response = self.get_response(request)
        return response


def get_impersonated_session_expires_at(request: HttpRequest) -> Optional[datetime]:
    if not is_impersonated_session(request):
        return None

    init_time = get_or_set_session_cookie_created_at(request=request)

    last_activity_time = request.session.get(settings.IMPERSONATION_COOKIE_LAST_ACTIVITY_KEY, init_time)

    # If the last activity time is less than the idle timeout, we extend the session
    if time.time() - last_activity_time < settings.IMPERSONATION_IDLE_TIMEOUT_SECONDS:
        last_activity_time = request.session[settings.IMPERSONATION_COOKIE_LAST_ACTIVITY_KEY] = time.time()
        request.session.modified = True

    idle_expiry_time = datetime.fromtimestamp(last_activity_time) + timedelta(
        seconds=settings.IMPERSONATION_IDLE_TIMEOUT_SECONDS
    )
    total_expiry_time = datetime.fromtimestamp(init_time) + timedelta(seconds=settings.IMPERSONATION_TIMEOUT_SECONDS)

    return min(idle_expiry_time, total_expiry_time)


class AutoLogoutImpersonateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        impersonated_session_expires_at = get_impersonated_session_expires_at(request)

        if not impersonated_session_expires_at:
            return self.get_response(request)

        session_is_expired = impersonated_session_expires_at < datetime.now()

        if session_is_expired:
            # TRICKY: We need to handle different cases here:
            # 1. For /api requests we want to respond with a code that will force the UI to redirect to the logout page (401)
            # 2. For any other endpoint we want to redirect to the logout page
            # 3. BUT we wan't to intercept the /logout endpoint so that we can restore the original login

            if request.path.startswith("/static/"):
                # Skip static files
                pass
            elif request.path.startswith("/api/"):
                return HttpResponse(
                    "Impersonation session has expired. Please log in again.",
                    status=401,
                )
            elif not request.path.startswith("/logout"):
                return redirect("/logout/")
            else:
                restore_original_login(request)
                return redirect("/admin/")

        return self.get_response(request)


class Fix204Middleware:
    """
    Remove the 'Content-Type' and 'X-Content-Type-Options: nosniff' headers and set content to empty string for HTTP 204 response (and only those).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if response.status_code == 204:
            response.content = b""
            for h in ["Content-Type", "X-Content-Type-Options"]:
                response.headers.pop(h, None)

        return response


# Add CSP to Admin tooling
class AdminCSPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_admin_view = request.path.startswith("/admin/")
        # add nonce to request before generating response
        if is_admin_view:
            nonce = generate_random_token(16)
            request.admin_csp_nonce = nonce

        response = self.get_response(request)

        if is_admin_view:
            # TODO replace with django-loginas `LOGINAS_CSP_FRIENDLY` setting once 0.3.12 is released (https://github.com/skorokithakis/django-loginas/issues/111)
            django_loginas_inline_script_hash = "sha256-YS9p0l7SQLkAEtvGFGffDcYHRcUBpPzMcbSQe1lRuLc="
            csp_parts = [
                "default-src 'self'",
                "style-src 'self' 'unsafe-inline'",
                f"script-src 'self' 'nonce-{nonce}' '{django_loginas_inline_script_hash}'",
                "worker-src 'none'",
                "child-src 'none'",
                "object-src 'none'",
                "frame-ancestors 'none'",
                "manifest-src 'none'",
                "base-uri 'self'",
                "report-uri https://us.i.posthog.com/report/?token=sTMFPsFhdP1Ssg&v=2",
                "report-to posthog",
            ]

            response.headers["Reporting-Endpoints"] = (
                'posthog="https://us.i.posthog.com/report/?token=sTMFPsFhdP1Ssg&v=2"'
            )
            response.headers["Content-Security-Policy"] = "; ".join(csp_parts)

        return response
