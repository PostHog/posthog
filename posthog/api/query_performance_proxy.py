"""OAuth-gated ClickHouse proxy for query-performance autoresearch.

One endpoint: ``POST /api/query_performance_proxy/execute-test/``. The cluster
behind ``CLICKHOUSE_PERF_TEST_HTTP_URL`` must be team-scoped at the ClickHouse
level — this proxy does no team filtering of its own. Deploy it against a test
cluster that contains only data the caller is authorized to see (today: team 2,
"PostHog, the company"), or against a ClickHouse user whose row policies
enforce the same restriction.

We deliberately do not expose a prod-cluster endpoint from this proxy: server-
side row-policy enforcement is the right place to gate cross-team reads, and a
regex-based SQL check at the Django layer is both fragile (trivially bypassed
via ``OR``, comments, string literals) and gives false confidence about what
the agent can read. If production traffic ever needs to be queried through
this flow, the correct path is a dedicated ClickHouse user with a row policy
plus a profile that pins ``readonly = 2`` as non-overridable.

Defence-in-depth here:
- ``scope_object = "INTERNAL"`` plus explicit OAuth scope ``clickhouse_perf:test_read``
- SQL must start with SELECT/WITH/EXPLAIN/SHOW/DESCRIBE/DESC (first-token check)
- Every submission is wrapped in ``SETTINGS max_execution_time = 60, readonly = 2``
"""

from __future__ import annotations

import re
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.permissions import APIScopePermission


class ExecuteRequestSerializer(serializers.Serializer):
    sql = serializers.CharField()


@dataclass(frozen=True)
class _ValidationError:
    message: str


_ACTION_SCOPES: dict[str, list[str]] = {
    "execute_test": ["clickhouse_perf:test_read"],
}


class QueryPerformanceProxyViewSet(viewsets.ViewSet):
    """Proxy for SELECT-only ClickHouse queries used by autoresearch sandboxes.

    Scope dispatch goes through :meth:`dangerously_get_required_scopes` so the
    action keeps its own scope without pulling in ``TeamAndOrgViewSetMixin``
    (which is designed for team-nested routes). ``scope_object = "INTERNAL"``
    still signals to ``ScopeBasePermission`` that the usual CRUD-derived
    default doesn't apply.
    """

    authentication_classes = [OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "INTERNAL"

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        return _ACTION_SCOPES.get(getattr(view, "action", "") or "")

    @action(detail=False, methods=["POST"], url_path="execute-test")
    def execute_test(self, request: Request) -> Response:
        cluster_url = getattr(settings, "CLICKHOUSE_PERF_TEST_HTTP_URL", None)
        if not cluster_url:
            return Response(
                {"error": "CLICKHOUSE_PERF_TEST_HTTP_URL is not configured; test endpoint disabled"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return self._execute(request, cluster_url=cluster_url)

    def _execute(self, request: Request, *, cluster_url: str) -> Response:
        serializer = ExecuteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sql: str = serializer.validated_data["sql"]

        if err := _validate_readonly_sql(sql):
            return Response({"error": err.message}, status=status.HTTP_400_BAD_REQUEST)

        return _proxy_to_clickhouse(cluster_url, sql)


# -------------------------------------------------------------- validation --

_READ_ONLY_KEYWORDS = frozenset({"SELECT", "WITH", "EXPLAIN", "SHOW", "DESCRIBE", "DESC"})
_COMMENT_RE = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)
_FIRST_TOKEN_RE = re.compile(r"^\s*(\w+)")


def _validate_readonly_sql(sql: str) -> _ValidationError | None:
    """Reject anything that isn't a SELECT/WITH/EXPLAIN/SHOW statement.

    Intentionally simple: strips comments, checks the first token. ClickHouse
    will also enforce ``readonly=2`` server-side (see :func:`_proxy_to_clickhouse`)
    — this layer is defense-in-depth plus a nicer error message.
    """
    stripped = _COMMENT_RE.sub("", sql)
    match = _FIRST_TOKEN_RE.match(stripped)
    if not match:
        return _ValidationError("sql is empty or does not start with a statement keyword")
    keyword = match.group(1).upper()
    if keyword not in _READ_ONLY_KEYWORDS:
        return _ValidationError(
            f"sql must begin with a read-only statement (one of: "
            f"{', '.join(sorted(_READ_ONLY_KEYWORDS))}); got: {keyword}"
        )
    return None


# ------------------------------------------------------------------- proxy --

_CLICKHOUSE_SETTINGS_SUFFIX = "\nSETTINGS max_execution_time = 60, readonly = 2"
_PROXY_TIMEOUT_S = 70  # Slight buffer over the ClickHouse-side max_execution_time.


def _proxy_to_clickhouse(base_url: str, sql: str) -> Response:
    url = base_url.rstrip("/") + "/?default_format=TSV"
    body = (sql + _CLICKHOUSE_SETTINGS_SUFFIX).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=_PROXY_TIMEOUT_S) as resp:  # noqa: S310 — configured internal URL
            payload = resp.read()
            headers = resp.headers
    except urllib.error.HTTPError as e:
        return Response(
            {
                "error": f"clickhouse responded {e.code}",
                "detail": e.read().decode("utf-8", "replace")[:2000],
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except urllib.error.URLError as e:
        return Response({"error": f"clickhouse unreachable: {e}"}, status=status.HTTP_502_BAD_GATEWAY)
    elapsed_ms = (time.monotonic() - start) * 1000.0

    rows_read, bytes_read = _parse_summary(headers.get("X-ClickHouse-Summary") or "")

    return Response(
        {
            "result": payload.decode("utf-8", "replace"),
            "elapsed_ms": round(elapsed_ms, 3),
            "rows_read": rows_read,
            "bytes_read": bytes_read,
            "query_id": headers.get("X-ClickHouse-Query-Id"),
        },
        status=status.HTTP_200_OK,
    )


def _parse_summary(summary: str) -> tuple[int | None, int | None]:
    if not summary:
        return None, None
    try:
        data = json.loads(summary)
    except json.JSONDecodeError:
        return None, None
    return _coerce_int(data.get("read_rows")), _coerce_int(data.get("read_bytes"))


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
