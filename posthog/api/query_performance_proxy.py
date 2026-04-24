"""OAuth-gated ClickHouse passthrough for the query-performance autoresearch sandbox.

Dev-only for now (DEBUG gate). All SQL safety comes from the ClickHouse user
routed through ``CLICKHOUSE_TEST_CLUSTER_*``: readonly=2 pinned in the profile
(no writes, no settings overrides), no grants on table functions like
``url()``/``s3()``/``file()``/``executable()``/``jdbc()`` (so SSRF and exec
surfaces are rejected by CH itself with a GRANT error), and SELECT grants
limited to the tables relevant to query-performance work. The Django layer
does NOT parse or filter SQL — regex-based SQL filtering is unsafe and we
rely on CH's own authorization.

Local dev user: ``autoresearch`` (see ``docker/clickhouse/users-dev.xml``),
set as the default in ``bin/start``. Prod enablement requires an equivalent
user on the real test cluster.
"""

from __future__ import annotations

import logging
import threading

from django.conf import settings

from clickhouse_driver import Client as SyncClient
from clickhouse_driver import errors as clickhouse_driver_errors
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


# Single-tenant test cluster: we serialize all proxy calls with _QUERY_LOCK so
# only one query runs at a time. Wall-clock caps the worst iteration; the row
# and byte caps make ClickHouse throw (not truncate) on overflow so a runaway
# `SELECT *` fails loud instead of poisoning the compare oracle. These caps
# live here (not in the CH user profile) because this endpoint is the only
# caller with these credentials, so iterating in code is safe. `readonly=2`
# IS pinned in the profile — the load-bearing safety — and we also pass it
# below for belt-and-suspenders. The SQL length cap is a Python-memory bound,
# not a security check; SQL safety comes from the CH user's grants.
MAX_SQL_LENGTH = 64 * 1024
MAX_EXECUTION_TIME_SECONDS = 5 * 60
MAX_RESULT_ROWS = 10_000
MAX_RESULT_BYTES = 10 * 1024 * 1024  # 10 MiB


class ExecuteRequestSerializer(serializers.Serializer):
    sql = serializers.CharField(max_length=MAX_SQL_LENGTH)


_ACTION_SCOPES: dict[str, list[str]] = {
    "execute_test": ["clickhouse_test_cluster_perf:test_read"],
}

_QUERY_SETTINGS: dict[str, object] = {
    "max_execution_time": MAX_EXECUTION_TIME_SECONDS,
    "max_result_rows": MAX_RESULT_ROWS,
    "max_result_bytes": MAX_RESULT_BYTES,
    # "throw" so the caller sees a concrete CH error code on overflow and can
    # narrow the query, rather than silently receiving a truncated result (the
    # comparison oracle would then crown a wrong query as "fast + correct").
    "result_overflow_mode": "throw",
    "readonly": 2,
}


# Module-level client cache + lock. `clickhouse-driver.Client` owns a TCP (+
# TLS) connection and exposes per-connection mutable state (`last_query`), so
# any concurrent use corrupts both the wire protocol and the metrics we return.
# We guard with a single `_QUERY_LOCK` held across the full `sync_execute` +
# `last_query` read: one query at a time on the test cluster is what we want
# anyway (single-tenant; concurrent workloads would be noisy neighbours).
_SYNC_CLIENT: SyncClient | None = None
_SYNC_CLIENT_KEY: tuple | None = None
_QUERY_LOCK = threading.Lock()


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
    """Drop the cached SyncClient. Called from the connection-failure branch in
    `_run_autoresearch_query` (under `_QUERY_LOCK`) and from test setUp (no
    lock — test context is single-threaded)."""
    global _SYNC_CLIENT, _SYNC_CLIENT_KEY
    if _SYNC_CLIENT is not None:
        try:
            _SYNC_CLIENT.disconnect()
        except Exception:
            logger.debug("sync client disconnect raised during reset", exc_info=True)
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
    # Single global lock: protects `SyncClient` mutable state AND enforces the
    # single-tenant test cluster's "one query at a time" invariant.
    with _QUERY_LOCK:
        client = _get_sync_client()
        try:
            with tags_context(product=Product.INTERNAL, feature=Feature.AUTORESEARCH):
                rows = sync_execute(sql, settings=_QUERY_SETTINGS, sync_client=client, flush=False)
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
        except (
            ConnectionError,
            OSError,  # covers socket.error, BrokenPipeError, TimeoutError
            EOFError,
            clickhouse_driver_errors.NetworkError,
            clickhouse_driver_errors.SocketTimeoutError,
            clickhouse_driver_errors.UnexpectedPacketFromServerError,
            clickhouse_driver_errors.UnknownPacketFromServerError,
            clickhouse_driver_errors.PartiallyConsumedQueryError,
        ):
            # Connection-level failure leaves the cached client in an unknown
            # state; drop it so the next request reconnects rather than looping
            # on a zombie socket. Other exceptions (programmer errors like
            # UntaggedQueryError, AttributeError, etc.) propagate as 500 so we
            # don't flap a healthy socket on a code bug.
            logger.exception("query_performance_proxy: failed to reach ClickHouse")
            _reset_sync_client_cache()
            return Response(
                {"error": "clickhouse unreachable"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Metrics come from the driver's `last_query` info so they reflect
        # ClickHouse's own view (server-side elapsed, scan-side rows/bytes) —
        # autoresearch compares these across candidates. Read inside the lock
        # so a concurrent reset can't null the client between execute and read.
        last_query = getattr(client, "last_query", None)
        profile_info = getattr(last_query, "profile_info", None)
        elapsed_seconds = getattr(last_query, "elapsed", None)
        query_id = getattr(last_query, "query_id", None)

    return Response(
        {
            "result": rows if isinstance(rows, list) else [],
            "query_id": query_id,
            "elapsed_ms": round(elapsed_seconds * 1000.0, 3) if isinstance(elapsed_seconds, int | float) else None,
            "rows_read": getattr(profile_info, "rows", None),
            "bytes_read": getattr(profile_info, "bytes", None),
            "rows_returned": len(rows) if isinstance(rows, list) else None,
        },
        status=status.HTTP_200_OK,
    )
