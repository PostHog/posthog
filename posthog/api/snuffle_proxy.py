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
import threading
from concurrent.futures import ThreadPoolExecutor
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
from posthog.api_queries_budget import debit
from posthog.hogql_queries.query_runner import api_queries_budget_enforcement_enabled, get_api_queries_budget_status
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle
from posthog.security.outbound_proxy import internal_requests

logger = structlog.get_logger(__name__)

# This private-alpha flag gates all Snuffle proxy endpoints.
# New subclasses use the flag by default.
SNUFFLE_API_FEATURE_FLAG = "logs-metrics-snuffle-api"

TEAM_ID_HEADER = "X-Team-ID"
SNUFFLE_READ_BYTES_HEADER = "X-Snuffle-ClickHouse-Read-Bytes"
# Debit outside the response-critical path. The bound limits work retained in a web process if
# Redis is slow or unavailable; a skipped debit is safe because the budget deliberately fails open.
SNUFFLE_BUDGET_DEBIT_MAX_PENDING = 8
_snuffle_budget_debit_slots = threading.BoundedSemaphore(SNUFFLE_BUDGET_DEBIT_MAX_PENDING)
_snuffle_budget_debit_executor: ThreadPoolExecutor | None = None
_snuffle_budget_debit_executor_lock = threading.Lock()
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


def _read_bytes_from(upstream: requests.Response) -> int | None:
    """Read the total ClickHouse bytes that Snuffle reports for this request.

    A missing or malformed header means an older or unhealthy upstream. Metering
    must fail open in that case, like the shared query budget does.
    """
    value = upstream.headers.get(SNUFFLE_READ_BYTES_HEADER)
    if value is None:
        return None
    try:
        bytes_read = int(value)
    except (TypeError, ValueError):
        logger.warning("snuffle_proxy_invalid_read_bytes", value=value)
        return None
    return bytes_read if bytes_read >= 0 else None


def _get_snuffle_budget_debit_executor() -> ThreadPoolExecutor:
    # Start the threads in the serving worker rather than in a pre-fork parent process.
    global _snuffle_budget_debit_executor
    if _snuffle_budget_debit_executor is None:
        with _snuffle_budget_debit_executor_lock:
            if _snuffle_budget_debit_executor is None:
                _snuffle_budget_debit_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="snuffle-budget")
    return _snuffle_budget_debit_executor


def schedule_snuffle_budget_debit(team_id: str, bytes_read: int) -> None:
    """Debit the query budget without delaying a completed Snuffle response."""
    if not _snuffle_budget_debit_slots.acquire(blocking=False):
        logger.warning("snuffle_proxy_budget_debit_skipped", team_id=team_id, reason="saturated")
        return

    def _debit() -> None:
        try:
            debit(team_id, bytes_read)
        except Exception:
            logger.exception("snuffle_proxy_budget_debit_failed", team_id=team_id)
        finally:
            _snuffle_budget_debit_slots.release()

    try:
        _get_snuffle_budget_debit_executor().submit(_debit)
    except Exception:
        _snuffle_budget_debit_slots.release()
        logger.exception("snuffle_proxy_budget_debit_submit_failed", team_id=team_id)


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
    posthog_feature_flag = SNUFFLE_API_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission]
    # The Prometheus and Loki APIs take POST bodies as form fields, the same shape as the query string.
    parser_classes = [FormParser]
    # Kept as a fallback until the upstream version that reports read bytes is deployed.
    # The byte-budget flag removes these request-count limits before the proxy action runs.
    throttle_classes = [ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle]

    def _is_api_queries_budget_enforced(self) -> bool:
        if not hasattr(self, "_api_queries_budget_enforced"):
            self._api_queries_budget_enforced = api_queries_budget_enforcement_enabled(self.team)
        return self._api_queries_budget_enforced

    def get_throttles(self):
        if self._is_api_queries_budget_enforced():
            return []
        return super().get_throttles()

    @extend_schema(exclude=True)
    @action(detail=False, methods=["GET", "POST"], url_path=r"api/v1/(?P<path>[A-Za-z0-9_./-]+)")
    def proxy(self, request: Request, path: str, **kwargs) -> HttpResponse:
        # The router's trailing slash is optional and the path group can capture it, so without
        # this `.../api/v1/query/` misses the allowlist while `.../api/v1/query` matches.
        path = path.rstrip("/")
        if not any(pattern.fullmatch(path) for pattern in self.allowed_paths):
            return _error_response(status.HTTP_404_NOT_FOUND, "not_found", f"unsupported endpoint: {path}")

        base_url = settings.SNUFFLE_APM_URL
        if not base_url:
            return _error_response(
                status.HTTP_501_NOT_IMPLEMENTED, "unavailable", "PromQL/LogQL query API is not configured"
            )

        team_id = self.team_id
        enforcement_enabled = self._is_api_queries_budget_enforced()
        budget_status = get_api_queries_budget_status(self.team) if enforcement_enabled else None
        if budget_status is not None and budget_status.remaining_bytes <= 0:
            response = _error_response(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "rate_limited",
                "ClickHouse query byte budget exhausted. Try again later.",
            )
            response["Retry-After"] = str(budget_status.retry_after_seconds)
            return response

        method = request.method or "GET"
        url = f"{base_url.rstrip('/')}{self.upstream_prefix}/{path}"
        params = _forwardable(request.query_params)
        headers = {TEAM_ID_HEADER: str(team_id), "Accept": request.headers.get("Accept", "application/json")}
        body = _forwardable(request.data) if method == "POST" and isinstance(request.data, QueryDict) else None
        auth = (settings.SNUFFLE_APM_USER, settings.SNUFFLE_APM_PASSWORD) if settings.SNUFFLE_APM_USER else None

        try:
            upstream = internal_requests.request(
                method,
                url,
                params=params,
                data=body,
                headers=headers,
                auth=auth,
                timeout=settings.SNUFFLE_APM_TIMEOUT_SECONDS,
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

        response = HttpResponse(
            upstream.content,
            status=upstream.status_code,
            content_type=upstream.headers.get("Content-Type", "application/json"),
        )
        bytes_read = _read_bytes_from(upstream)
        if bytes_read is not None:
            schedule_snuffle_budget_debit(str(team_id), bytes_read)
            response["X-PostHog-Query-Bytes-Read"] = str(bytes_read)
        return response
