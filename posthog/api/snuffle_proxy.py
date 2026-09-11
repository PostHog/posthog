"""Proxy PromQL and LogQL queries to Snuffle.

Snuffle (https://github.com/PostHog/snuffle) is the PromQL/LogQL bridge deployed alongside the
logs ClickHouse cluster. It speaks the Prometheus and Loki HTTP APIs and translates them to
ClickHouse SQL. PostHog owns authentication and tenant resolution: the viewset resolves the team
from the URL and forwards the request with an ``X-Team-ID`` header, which Snuffle turns into a
tenant filter on every ClickHouse query. Snuffle's own credential is the ClickHouse user, sent as
HTTP Basic auth and never exposed to the API caller.
"""

import re
import json
from typing import ClassVar

from django.conf import settings
from django.http import HttpResponse, QueryDict

import requests
import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.security.outbound_proxy import internal_requests

logger = structlog.get_logger(__name__)

TEAM_ID_HEADER = "X-Team-ID"
# Snuffle also accepts the tenant as a `team_id` parameter, with lower precedence than the header;
# strip it so the forwarded request only ever names the team from the URL. PostHog accepts the
# caller's personal API key as a parameter too, and that must never leave PostHog.
STRIPPED_PARAMS = frozenset({"team_id", "personal_api_key"})


def _forwardable(params: QueryDict) -> dict[str, list[str]]:
    return {key: values for key, values in params.lists() if key not in STRIPPED_PARAMS}


def _error_response(status_code: int, error_type: str, message: str) -> HttpResponse:
    # Prometheus/Loki error envelope, so clients surface `error` the same way they do for
    # upstream failures.
    return HttpResponse(
        json.dumps({"status": "error", "errorType": error_type, "error": message}),
        status=status_code,
        content_type="application/json",
    )


class SnuffleProxyViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Base for the team-scoped Prometheus- and Loki-compatible query endpoints.

    Subclasses set ``scope_object``, ``upstream_prefix`` (the Snuffle path the ``api/v1/``
    suffix maps onto) and ``allowed_paths`` (read-only endpoints, matched against the rest
    of the path). Anything else, including remote write and push, is rejected before it
    leaves PostHog.
    """

    upstream_prefix: ClassVar[str]
    allowed_paths: ClassVar[tuple[re.Pattern[str], ...]]

    scope_object_read_actions = ["proxy"]
    # The Prometheus and Loki APIs take POST bodies as form fields, the same shape as the query string.
    parser_classes = [FormParser]
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]

    @extend_schema(exclude=True)
    @action(detail=False, methods=["GET", "POST"], url_path=r"api/v1/(?P<path>[A-Za-z0-9_./-]+)")
    def proxy(self, request: Request, path: str, **kwargs) -> HttpResponse:
        if not any(pattern.fullmatch(path) for pattern in self.allowed_paths):
            return _error_response(status.HTTP_404_NOT_FOUND, "not_found", f"unsupported endpoint: {path}")

        base_url = settings.SNUFFLE_URL
        if not base_url:
            return _error_response(
                status.HTTP_501_NOT_IMPLEMENTED, "unavailable", "PromQL/LogQL query API is not configured"
            )

        team_id = self.team_id
        method = request.method or "GET"
        url = f"{base_url.rstrip('/')}{self.upstream_prefix}/{path}"
        params = _forwardable(request.query_params)
        headers = {TEAM_ID_HEADER: str(team_id), "Accept": request.headers.get("Accept", "application/json")}
        body = _forwardable(request.data) if method == "POST" and isinstance(request.data, QueryDict) else None
        auth = (settings.SNUFFLE_USER, settings.SNUFFLE_PASSWORD) if settings.SNUFFLE_USER else None

        try:
            upstream = internal_requests.request(
                method,
                url,
                params=params,
                data=body,
                headers=headers,
                auth=auth,
                timeout=settings.SNUFFLE_TIMEOUT_SECONDS,
            )
        except requests.Timeout:
            logger.warning("snuffle_proxy_timeout", team_id=team_id, path=path)
            return _error_response(status.HTTP_504_GATEWAY_TIMEOUT, "timeout", "query timed out")
        except requests.RequestException:
            logger.exception("snuffle_proxy_unreachable", team_id=team_id, path=path)
            return _error_response(status.HTTP_502_BAD_GATEWAY, "unavailable", "query backend is unreachable")

        if upstream.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            # Snuffle only rejects the ClickHouse credential we sent, never the caller, so this is
            # our misconfiguration and must not read as the caller's auth failure.
            logger.error("snuffle_proxy_rejected_credentials", team_id=team_id, path=path, status=upstream.status_code)
            return _error_response(status.HTTP_502_BAD_GATEWAY, "unavailable", "query backend rejected the request")
        if upstream.status_code >= 500:
            logger.warning("snuffle_proxy_upstream_error", team_id=team_id, path=path, status=upstream.status_code)

        return HttpResponse(
            upstream.content,
            status=upstream.status_code,
            content_type=upstream.headers.get("Content-Type", "application/json"),
        )
