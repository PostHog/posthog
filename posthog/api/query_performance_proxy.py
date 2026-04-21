"""OAuth-gated ClickHouse proxy for query-performance autoresearch.

Two endpoints, one per cluster. The split into separate URLs — rather than one
endpoint that dispatches on a ``cluster`` body field — lets us use DRF's static
``required_scopes`` machinery and keeps the auth model easy to audit at a
glance: if a caller hit ``/execute-prod``, their token had prod_read scope.

Prod-bound queries must filter on ``team_id = 2``. The endpoint **rejects**
queries that lack the predicate rather than rewriting them — callers own
correctness, and a 400 tells an agent to retry with a corrected query.
"""

from __future__ import annotations

import json
import re
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

# team_id = 2 is "PostHog, the company" in prod; the test cluster is pre-filled
# with that team's data. Keeping this constant at the module level makes the
# security model searchable.
PROD_ALLOWED_TEAM_ID = 2


class ExecuteRequestSerializer(serializers.Serializer):
    sql = serializers.CharField()


@dataclass(frozen=True)
class _ValidationError:
    message: str


_ACTION_SCOPES: dict[str, list[str]] = {
    "execute_test": ["clickhouse_perf:test_read"],
    "execute_prod": ["clickhouse_perf:prod_read"],
}


class QueryPerformanceProxyViewSet(viewsets.ViewSet):
    """Proxy for SELECT-only ClickHouse queries used by autoresearch sandboxes.

    Scope dispatch goes through :meth:`dangerously_get_required_scopes` so
    each action keeps its own scope without pulling in
    ``TeamAndOrgViewSetMixin`` (which is designed for team-nested routes).
    ``scope_object = "INTERNAL"`` still signals to ``ScopeBasePermission``
    that the usual CRUD-derived default doesn't apply.
    """

    authentication_classes = [OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "INTERNAL"

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        return _ACTION_SCOPES.get(getattr(view, "action", "") or "")

    @action(detail=False, methods=["POST"], url_path="execute-test")
    def execute_test(self, request: Request) -> Response:
        return self._execute(request, cluster_url=settings.CLICKHOUSE_PERF_TEST_HTTP_URL, allow_any_team=True)

    @action(detail=False, methods=["POST"], url_path="execute-prod")
    def execute_prod(self, request: Request) -> Response:
        return self._execute(request, cluster_url=settings.CLICKHOUSE_PERF_PROD_HTTP_URL, allow_any_team=False)

    def _execute(self, request: Request, *, cluster_url: str, allow_any_team: bool) -> Response:
        serializer = ExecuteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sql: str = serializer.validated_data["sql"]

        if err := _validate_readonly_sql(sql):
            return Response({"error": err.message}, status=status.HTTP_400_BAD_REQUEST)

        if not allow_any_team:
            if err := _validate_team_scoping(sql, required_team_id=PROD_ALLOWED_TEAM_ID):
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
    — this layer is defence-in-depth plus a nicer error message.
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


def _team_id_patterns(required_team_id: int) -> tuple[re.Pattern[str], ...]:
    # Accept both ``team_id = 2`` and ``team_id IN (2)`` with flexible whitespace
    # / casing. Deliberately narrow so an agent can't bypass with tricks like
    # ``team_id = 1 + 1`` — if the literal predicate isn't present we fail out.
    return (
        re.compile(rf"\bteam_id\s*=\s*{required_team_id}\b", re.IGNORECASE),
        re.compile(rf"\bteam_id\s+IN\s*\(\s*{required_team_id}\s*\)", re.IGNORECASE),
    )


def _validate_team_scoping(sql: str, *, required_team_id: int) -> _ValidationError | None:
    for pattern in _team_id_patterns(required_team_id):
        if pattern.search(sql):
            return None
    return _ValidationError(
        f"queries against the prod cluster must filter to team_id = {required_team_id} "
        "using a literal predicate (team_id = N or team_id IN (N)); this endpoint never rewrites queries"
    )


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
