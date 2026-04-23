"""OAuth-gated ClickHouse passthrough for the query-performance autoresearch sandbox.

Dev-only for now (DEBUG gate). The test cluster behind ``CLICKHOUSE_TEST_CLUSTER_HOST``
must only contain data we're willing to point an autoresearch LLM at — today,
team 2. SQL is not validated at the Django layer; protection comes from the
ClickHouse user's readonly profile + the limited scope of data on the cluster.

Once DEBUG is dropped, enabling this in prod also requires a locked-down CH
user (readonly=2 pinned in the profile, row policies for team scoping).
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

from clickhouse_driver import Client as SyncClient
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.errors import InternalCHQueryError
from posthog.permissions import APIScopePermission

logger = logging.getLogger(__name__)


# Single-tenant cluster, so we don't need caps aimed at protecting the CH side
# itself — wall-clock is what bounds how long one iteration can stall the
# campaign loop. The row / byte caps here protect the _Django worker_: the
# proxy materializes the result list in memory before DRF-serializing it, so
# one LLM-drafted `SELECT *` on `events` would otherwise OOM the web process.
MAX_EXECUTION_TIME_SECONDS = 5 * 60
MAX_RESULT_ROWS = 10_000
MAX_RESULT_BYTES = 10 * 1024 * 1024  # 10 MiB


class ExecuteRequestSerializer(serializers.Serializer):
    sql = serializers.CharField()


_ACTION_SCOPES: dict[str, list[str]] = {
    "execute_test": ["clickhouse_test_cluster_perf:test_read"],
}

_QUERY_SETTINGS: dict[str, object] = {
    "max_execution_time": MAX_EXECUTION_TIME_SECONDS,
    "max_result_rows": MAX_RESULT_ROWS,
    "max_result_bytes": MAX_RESULT_BYTES,
    # "throw" so the caller sees a concrete CH error code on overflow and can
    # narrow the query, rather than silently receiving a truncated result.
    "result_overflow_mode": "throw",
    "readonly": 2,
}


# Module-level client cache. `clickhouse-driver.Client` owns a TCP (+ TLS)
# connection and exposes per-connection state (`last_query`), so reusing one
# avoids a handshake per request. Keyed on the connection settings tuple so
# test `override_settings(CLICKHOUSE_TEST_CLUSTER_HOST=...)` rebuilds.
#
# The endpoint is DEBUG-gated and single-operator today; when that changes a
# proper thread-local / pool will be needed because `last_query` is mutable
# per-client state.
_SYNC_CLIENT: SyncClient | None = None
_SYNC_CLIENT_KEY: tuple | None = None


def _get_sync_client() -> SyncClient:
    global _SYNC_CLIENT, _SYNC_CLIENT_KEY
    key = (
        settings.CLICKHOUSE_TEST_CLUSTER_HOST,
        settings.CLICKHOUSE_TEST_CLUSTER_DATABASE,
        settings.CLICKHOUSE_TEST_CLUSTER_USER,
        settings.CLICKHOUSE_TEST_CLUSTER_PASSWORD,
        settings.CLICKHOUSE_TEST_CLUSTER_SECURE,
        settings.CLICKHOUSE_TEST_CLUSTER_CA,
        settings.CLICKHOUSE_TEST_CLUSTER_VERIFY,
    )
    if _SYNC_CLIENT is None or _SYNC_CLIENT_KEY != key:
        _SYNC_CLIENT = SyncClient(
            host=key[0],
            database=key[1],
            user=key[2],
            password=key[3],
            secure=key[4],
            ca_certs=key[5],
            verify=key[6],
        )
        _SYNC_CLIENT_KEY = key
    return _SYNC_CLIENT


def _reset_sync_client_cache() -> None:
    """Test-only: clear the module-level client cache between tests."""
    global _SYNC_CLIENT, _SYNC_CLIENT_KEY
    _SYNC_CLIENT = None
    _SYNC_CLIENT_KEY = None


class QueryPerformanceProxyViewSet(viewsets.ViewSet):
    authentication_classes = [OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "INTERNAL"

    # Not project-nested: no URL team to validate scoped_teams against. Access
    # is gated by clickhouse_test_cluster_perf:test_read + DEBUG + the CH user's profile.
    dangerously_skip_scoped_team_enforcement = True

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        return _ACTION_SCOPES.get(getattr(view, "action", "") or "")

    @action(detail=False, methods=["POST"], url_path="execute-test")
    def execute_test(self, request: Request) -> Response:
        if not settings.DEBUG:
            return Response(
                {"error": "query_performance_proxy is only available when DEBUG is set"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not settings.CLICKHOUSE_TEST_CLUSTER_HOST:
            return Response(
                {"error": "CLICKHOUSE_TEST_CLUSTER_HOST is not configured; test endpoint disabled"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        serializer = ExecuteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _run_autoresearch_query(serializer.validated_data["sql"])


# ---------------------------------------------------------------- execution --


def _run_autoresearch_query(sql: str) -> Response:
    client = _get_sync_client()
    try:
        # Required: sync_execute raises UntaggedQueryError in DEBUG without these tags.
        with tags_context(product=Product.INTERNAL, feature=Feature.QUERY):
            rows = sync_execute(sql, settings=_QUERY_SETTINGS, sync_client=client, readonly=True, flush=False)
    except InternalCHQueryError as e:
        # Response carries only the CH error code — CodeQL flags returning
        # exception text as information exposure.
        logger.exception("query_performance_proxy: clickhouse query failed")
        return Response(
            {
                "error": "clickhouse query failed",
                "code": getattr(e, "code", None),
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception:
        logger.exception("query_performance_proxy: failed to reach ClickHouse")
        return Response(
            {"error": "clickhouse unreachable"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # All the metrics come from the driver's `last_query` info so they reflect
    # ClickHouse's own view of the query (server-side elapsed, scan-side
    # rows/bytes) — autoresearch compares these across candidates.
    last_query = getattr(client, "last_query", None)
    profile_info = getattr(last_query, "profile_info", None)
    elapsed_seconds = getattr(last_query, "elapsed", None)

    return Response(
        {
            "result": rows if isinstance(rows, list) else [],
            "query_id": getattr(last_query, "query_id", None),
            "elapsed_ms": round(elapsed_seconds * 1000.0, 3) if isinstance(elapsed_seconds, int | float) else None,
            "rows_read": getattr(profile_info, "rows", None),
            "bytes_read": getattr(profile_info, "bytes", None),
            "rows_returned": len(rows) if isinstance(rows, list) else None,
        },
        status=status.HTTP_200_OK,
    )
