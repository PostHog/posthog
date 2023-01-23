import time
from ipaddress import ip_address, ip_network
from typing import List, Optional, cast

from corsheaders.middleware import CorsMiddleware
from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.db import connection
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.urls.base import resolve
from django.utils.cache import add_never_cache_headers
from django_prometheus.middleware import PrometheusAfterMiddleware, PrometheusBeforeMiddleware
from django_statsd.middleware import StatsdMiddleware, StatsdMiddlewareTimer
from statshog.defaults.django import statsd

from posthog.api.capture import get_event
from posthog.api.decide import get_decide
from posthog.clickhouse.client.execute import clickhouse_query_counter
from posthog.clickhouse.query_tagging import QueryCounter, reset_query_tags, tag_queries
from posthog.models import Action, Cohort, Dashboard, FeatureFlag, Insight, Team, User
from posthog.settings.statsd import STATSD_HOST

from .auth import PersonalAPIKeyAuthentication

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
            target_queryset = self.get_target_queryset(request)
            if target_queryset is not None:
                self.switch_team_if_needed_and_possible(request, target_queryset)
        response = self.get_response(request)
        return response

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

    def switch_team_if_needed_and_possible(self, request: HttpRequest, target_queryset: QuerySet):
        user = cast(User, request.user)
        current_team = user.team
        if current_team is not None and not target_queryset.filter(team=current_team).exists():
            actual_item = target_queryset.only("team").select_related("team").first()
            if actual_item is not None:
                actual_item_team: Team = actual_item.team
                if actual_item_team.get_effective_membership_level(user.id) is not None:
                    user.current_team = actual_item_team
                    user.current_organization_id = actual_item_team.organization_id
                    user.save()
                    # Information for POSTHOG_APP_CONTEXT
                    request.switched_team = current_team.id  # type: ignore


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
        )

        if hasattr(user, "current_team_id") and user.current_team_id:
            tag_queries(team_id=user.current_team_id)

        try:
            response: HttpResponse = self.get_response(request)

            if "api/" in request.path and "capture" not in request.path:
                statsd.incr("http_api_request_response", tags={"id": route_id, "status_code": response.status_code})

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
    ALLOW_LIST_ROUTES = ["dashboard", "insight", "property_definitions", "properties"]

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

    def __call__(self, request: HttpRequest):
        if request.path == "/decide/" or request.path == "/decide":
            try:
                # :KLUDGE: Manually tag ClickHouse queries as CHMiddleware is skipped
                tag_queries(
                    kind="request",
                    id=request.path,
                    route_id=resolve(request.path).route,
                    container_hostname=settings.CONTAINER_HOSTNAME,
                )
                return get_decide(request)
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
        self.CAPTURE_MIDDLEWARE = [
            PrometheusBeforeMiddleware(),
            CorsMiddleware(),
            PrometheusAfterMiddleware(),
        ]

        if STATSD_HOST is not None:
            self.CAPTURE_MIDDLEWARE.insert(0, StatsdMiddleware())
            self.CAPTURE_MIDDLEWARE.append(StatsdMiddlewareTimer())

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
                )

                for middleware in self.CAPTURE_MIDDLEWARE:
                    middleware.process_request(request)

                response: HttpResponse = get_event(request)

                for middleware in self.CAPTURE_MIDDLEWARE[::-1]:
                    middleware.process_response(request, response)

                return response
            finally:
                reset_query_tags()

        response = self.get_response(request)
        return response
