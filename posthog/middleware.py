import time
from ipaddress import ip_address, ip_network
from typing import Any, Callable, List, Optional, cast

import structlog
from corsheaders.middleware import CorsMiddleware
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
    PrometheusAfterMiddleware,
    PrometheusBeforeMiddleware,
)
from rest_framework import status
from statshog.defaults.django import statsd

from posthog.api.capture import get_event
from posthog.api.decide import get_decide
from posthog.clickhouse.client.execute import clickhouse_query_counter
from posthog.clickhouse.query_tagging import QueryCounter, reset_query_tags, tag_queries
from posthog.cloud_utils import is_cloud
from posthog.exceptions import generate_exception_response
from posthog.metrics import LABEL_TEAM_ID
from posthog.models import Action, Cohort, Dashboard, FeatureFlag, Insight, Notebook, User, Team
from posthog.rate_limit import DecideRateThrottle
from posthog.settings import SITE_URL, DEBUG
from posthog.user_permissions import UserPermissions
from .auth import PersonalAPIKeyAuthentication
from .utils_cors import cors_response

ALWAYS_ALLOWED_ENDPOINTS = [
    "decide",
    "engage",
    "track",
    "capture",
    "batch",
    "e",
    "s",
    "static",
    "_health",
]

if DEBUG:
    # /i/ is the new root path for capture endpoints
    ALWAYS_ALLOWED_ENDPOINTS.append("i")

default_cookie_options = {
    "max_age": 365 * 24 * 60 * 60,  # one year
    "expires": None,
    "path": "/",
    "domain": "posthog.com",
    "secure": True,
    "samesite": "Strict",
}

cookie_api_paths_to_ignore = {"e", "s", "capture", "batch", "decide", "api", "track"}


class AllowIPMiddleware:
    trusted_proxies: List[str] = []

    def __init__(self, get_response):
        if not settings.ALLOWED_IP_BLOCKS:
            # this will make Django skip this middleware for all future requests
            raise MiddlewareNotUsed()
        self.ip_blocks = settings.ALLOWED_IP_BLOCKS

        if settings.TRUSTED_PROXIES:
            self.trusted_proxies = [item.strip() for item in settings.TRUSTED_PROXIES.split(",")]
        self.get_response = get_response

    def get_forwarded_for(self, request: HttpRequest):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for is not None:
            return [ip.strip() for ip in forwarded_for.split(",")]
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
                proxies = [closest_proxy] + forwarded_for
                for proxy in proxies:
                    if proxy not in self.trusted_proxies:
                        return None
        return client_ip

    def __call__(self, request: HttpRequest):
        response: HttpResponse = self.get_response(request)
        if request.path.split("/")[1] in ALWAYS_ALLOWED_ENDPOINTS:
            return response
        ip = self.extract_client_ip(request)
        if ip and any(ip_address(ip) in ip_network(block, strict=False) for block in self.ip_blocks):
            return response
        return HttpResponse(
            "Your IP is not allowed. Check your ALLOWED_IP_BLOCKS settings. If you are behind a proxy, you need to set TRUSTED_PROXIES. See https://posthog.com/docs/deployment/running-behind-proxy",
            status=403,
        )


class CsrfOrKeyViewMiddleware(CsrfViewMiddleware):
    """Middleware accepting requests that either contain a valid CSRF token or a personal API key."""

    def process_view(self, request, callback, callback_args, callback_kwargs):
        result = super().process_view(request, callback, callback_args, callback_kwargs)  # None if request accepted
        # if super().process_view did not find a valid CSRF token, try looking for a personal API key
        if result is not None and PersonalAPIKeyAuthentication.find_key_with_source(request) is not None:
            return self._accept(request)
        if DEBUG and request.path.split("/")[1] in ALWAYS_ALLOWED_ENDPOINTS:
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

    def __call__(self, request: HttpRequest):
        if request.user.is_authenticated:
            path_parts = request.path.strip("/").split("/")
            project_id_in_url = None
            if len(path_parts) >= 2 and path_parts[0] == "project" and path_parts[1].isdigit():
                project_id_in_url = int(path_parts[1])
            elif (
                len(path_parts) >= 3
                and path_parts[0] == "api"
                and path_parts[1] == "project"
                and path_parts[2].isdigit()
            ):
                project_id_in_url = int(path_parts[2])

            if (
                project_id_in_url is not None
                and request.user.team is not None
                and request.user.team.pk != project_id_in_url
            ):
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
        user_permissions = UserPermissions(user)
        # :KLUDGE: This is more inefficient than needed, doing several expensive lookups
        #   However this should be a rare operation!
        if user_permissions.team(new_team).effective_membership_level is None:
            # Do something to indicate that they don't have access to the team...
            return

        old_team_id = user.current_team_id
        user.team = new_team
        user.current_team = new_team
        user.current_organization_id = new_team.organization_id
        user.save()
        # Information for POSTHOG_APP_CONTEXT
        request.switched_team = old_team_id  # type: ignore


class CHQueries:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        """Install monkey-patch on demand.
        If monkey-patch has not been run in for this process (assuming multiple preforked processes),
        then do it now.
        """
        route = resolve(request.path)
        route_id = f"{route.route} ({route.func.__name__})"

        user = cast(User, request.user)

        tag_queries(
            user_id=user.pk,
            kind="request",
            id=request.path,
            route_id=route.route,
            client_query_id=self._get_param(request, "client_query_id"),
            session_id=self._get_param(request, "session_id"),
            container_hostname=settings.CONTAINER_HOSTNAME,
            http_referer=request.META.get("HTTP_REFERER"),
            http_user_agent=request.META.get("HTTP_USER_AGENT"),
        )

        if hasattr(user, "current_team_id") and user.current_team_id:
            tag_queries(team_id=user.current_team_id)

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
                    container_hostname=settings.CONTAINER_HOSTNAME,
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


class CaptureMiddleware:
    """
    Middleware to serve up capture responses. We specifically want to avoid
    doing any unnecessary work in these endpoints as they are hit very
    frequently, and we want to provide the best availability possible, which
    translates to keeping dependencies to a minimum.
    """

    def __init__(self, get_response):
        self.get_response = get_response

        middlewares: List[Any] = []
        # based on how we're using these middlewares, only middlewares that
        # have a process_request and process_response attribute can be valid here.
        # Or, middlewares that inherit from `middleware.util.deprecation.MiddlewareMixin` which
        # reconciles the old style middleware with the new style middleware.
        for middleware_class in (
            CorsMiddleware,
            PrometheusAfterMiddlewareWithTeamIds,
        ):
            try:
                # Some middlewares raise MiddlewareNotUsed if they are not
                # needed. In this case we want to avoid the default middlewares
                # being used.
                middlewares.append(middleware_class(get_response=get_response))
            except MiddlewareNotUsed:
                pass

        # List of middlewares we want to run, that would've been shortcircuited otherwise
        self.CAPTURE_MIDDLEWARE = middlewares

    def __call__(self, request: HttpRequest):
        if request.path in (
            "/e",
            "/e/",
            "/s",
            "/s/",
            "/track",
            "/track/",
            "/capture",
            "/capture/",
            "/batch",
            "/batch/",
            "/engage/",
            "/engage",
        ):
            try:
                # :KLUDGE: Manually tag ClickHouse queries as CHMiddleware is skipped
                tag_queries(
                    kind="request",
                    id=request.path,
                    route_id=resolve(request.path).route,
                    container_hostname=settings.CONTAINER_HOSTNAME,
                    http_referer=request.META.get("HTTP_REFERER"),
                    http_user_agent=request.META.get("HTTP_USER_AGENT"),
                )

                for middleware in self.CAPTURE_MIDDLEWARE:
                    middleware.process_request(request)

                # call process_view for PrometheusAfterMiddleware to get the right metrics in place
                # simulate how django prepares the url
                resolver_match = resolve(request.path)
                request.resolver_match = resolver_match
                for middleware in self.CAPTURE_MIDDLEWARE:
                    middleware.process_view(
                        request,
                        resolver_match.func,
                        resolver_match.args,
                        resolver_match.kwargs,
                    )

                response: HttpResponse = get_event(request)

                for middleware in self.CAPTURE_MIDDLEWARE[::-1]:
                    middleware.process_response(request, response)

                return response
            finally:
                reset_query_tags()

        response = self.get_response(request)
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

    This middleware adds some additional context at the beggining of the
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
        if name in PROMETHEUS_EXTENDED_METRICS:
            labelnames.extend([LABEL_TEAM_ID])
        return super().register_metric(metric_cls, name, documentation, labelnames=labelnames, **kwargs)


class PrometheusBeforeMiddlewareWithTeamIds(PrometheusBeforeMiddleware):
    metrics_cls = CustomPrometheusMetrics


class PrometheusAfterMiddlewareWithTeamIds(PrometheusAfterMiddleware):
    metrics_cls = CustomPrometheusMetrics

    def label_metric(self, metric, request, response=None, **labels):
        new_labels = labels
        if metric._name in PROMETHEUS_EXTENDED_METRICS:
            team_id = None
            if request and getattr(request, "user", None) and request.user.is_authenticated:
                if request.resolver_match.kwargs.get("parent_lookup_team_id"):
                    team_id = request.resolver_match.kwargs["parent_lookup_team_id"]
                    if team_id == "@current":
                        if hasattr(request.user, "current_team_id"):
                            team_id = request.user.current_team_id
                        else:
                            team_id = None

            new_labels = {LABEL_TEAM_ID: team_id}
            new_labels.update(labels)
        return super().label_metric(metric, request, response=response, **new_labels)


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
