"""OAuth-gated ClickHouse proxy for query-performance autoresearch.

One endpoint: ``POST /api/query_performance_proxy/execute-test/``. The cluster
behind ``CLICKHOUSE_PERF_TEST_HOST`` must be team-scoped at the ClickHouse
level — this proxy does no team filtering of its own. Deploy it against a test
cluster that contains only data the caller is authorized to see (today: team 2,
"PostHog, the company"), or against a ClickHouse user whose row policies
enforce the same restriction.

What this proxy enforces:

- ``scope_object = "INTERNAL"`` plus explicit OAuth scope ``clickhouse_perf:test_read``
  — gates who can reach the endpoint.
- ``settings={"max_execution_time": 60, "readonly": 2}`` on every query —
  bounds runtime and keeps reads read-only via the native ClickHouse client.

What the ClickHouse user the proxy connects as must enforce:

- ``readonly = 2`` pinned in the user's profile via ``<constraints>`` so a
  query-level override can't escape it.
- Row policies restricting the user to the team slice we're OK exposing.
- Grants limited to the tables the autoresearch agent is allowed to read.

We deliberately don't try to parse and validate SQL here. A regex-based
readonly / statement-kind check gives false confidence — the only honest
enforcement is the ClickHouse user profile plus the server-side settings we
pass. We also route through the native ClickHouse client (rather than
re-implementing HTTP proxying) so the same pooling / tagging / observability
machinery the rest of PostHog uses applies here too.
"""

from __future__ import annotations

import json
import time

from django.conf import settings

from clickhouse_driver import Client as SyncClient
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.clickhouse.client import sync_execute
from posthog.errors import InternalCHQueryError
from posthog.permissions import APIScopePermission


class ExecuteRequestSerializer(serializers.Serializer):
    sql = serializers.CharField()


_ACTION_SCOPES: dict[str, list[str]] = {
    "execute_test": ["clickhouse_perf:test_read"],
}

# Query-level settings we force on every submission. ``readonly = 2`` lets the
# query run but blocks mutations server-side. ``max_execution_time`` caps
# unbounded analytical queries so a bad pick can't wedge the cluster worker.
# ``log_comment`` makes the proxy's traffic identifiable in system.query_log.
_QUERY_SETTINGS: dict[str, object] = {
    "max_execution_time": 60,
    "readonly": 2,
    "log_comment": json.dumps({"kind": "query_performance_autoresearch_proxy"}),
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
        host = getattr(settings, "CLICKHOUSE_PERF_TEST_HOST", "")
        if not host:
            return Response(
                {"error": "CLICKHOUSE_PERF_TEST_HOST is not configured; test endpoint disabled"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return self._execute(request, host=host)

    def _execute(self, request: Request, *, host: str) -> Response:
        serializer = ExecuteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sql: str = serializer.validated_data["sql"]
        return _run_on_cluster(host, sql)


# ---------------------------------------------------------------- execution --


def _run_on_cluster(host: str, sql: str) -> Response:
    """Execute the caller's SQL against the autoresearch cluster.

    Builds a SyncClient pointed at ``host`` and hands it to ``sync_execute``
    so PostHog's standard query-tagging, metrics, and error-wrapping still
    apply. Credentials and TLS config come from the usual ``CLICKHOUSE_*``
    settings for now; a follow-up will split out a dedicated
    ``CLICKHOUSE_AUTORESEARCH_USER`` / _PASSWORD pair via the existing
    ``init_clickhouse_users`` mechanism.
    """
    client = SyncClient(
        host=host,
        database=settings.CLICKHOUSE_DATABASE,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        secure=settings.CLICKHOUSE_SECURE,
        ca_certs=settings.CLICKHOUSE_CA,
        verify=settings.CLICKHOUSE_VERIFY,
    )
    start = time.monotonic()
    try:
        rows = sync_execute(sql, settings=_QUERY_SETTINGS, sync_client=client, readonly=True, flush=False)
    except InternalCHQueryError as e:
        return Response(
            {"error": "clickhouse query failed", "detail": str(e)[:2000], "code": getattr(e, "code", None)},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as e:
        return Response(
            {"error": "clickhouse unreachable", "detail": str(e)[:2000]},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    elapsed_ms = (time.monotonic() - start) * 1000.0

    return Response(
        {
            # Autoresearch's baseline capture + per-run comparison rely on a
            # stable text blob to diff across iterations. Tab-separated rows
            # (newline-terminated) matches what the old ClickHouse HTTP
            # interface returned so the comparator doesn't need to change.
            "result": _rows_to_tsv(rows),
            "elapsed_ms": round(elapsed_ms, 3),
            "rows_read": len(rows) if isinstance(rows, list) else None,
            "bytes_read": None,
            "query_id": None,
        },
        status=status.HTTP_200_OK,
    )


def _rows_to_tsv(rows: object) -> str:
    if not isinstance(rows, list):
        return ""
    return "\n".join("\t".join(_cell(v) for v in row) for row in rows) + ("\n" if rows else "")


def _cell(value: object) -> str:
    if value is None:
        return "\\N"
    return str(value)
