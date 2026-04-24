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
from datetime import UTC, date, datetime
from decimal import Decimal
from ipaddress import IPv4Address, IPv6Address
from uuid import UUID

from django.conf import settings

from clickhouse_driver import (
    Client as SyncClient,
    errors as clickhouse_driver_errors,
)
from drf_spectacular.utils import extend_schema
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

# CLOUD_DEPLOYMENT values that identify a production/production-adjacent
# environment. If DEBUG is ever True in one of these (misconfig), the proxy
# must still refuse — DEBUG alone is one env-var flip away from exposing
# test-cluster data to anyone with the OAuth scope.
_PRODUCTION_CLOUD_DEPLOYMENTS = {"US", "EU", "DEV"}


class ExecuteRequestSerializer(serializers.Serializer):
    sql = serializers.CharField(max_length=MAX_SQL_LENGTH, help_text="ClickHouse SQL to run against the test cluster.")


class ExecuteResponseSerializer(serializers.Serializer):
    result = serializers.ListField(
        child=serializers.ListField(),
        help_text="Rows returned, each as a positional list of canonicalized values.",
    )
    query_id = serializers.CharField(allow_null=True, help_text="ClickHouse query_id for this execution.")
    elapsed_ms = serializers.FloatField(allow_null=True, help_text="Server-side elapsed time in milliseconds.")
    rows_read = serializers.IntegerField(allow_null=True, help_text="Rows read from storage (scan-side).")
    bytes_read = serializers.IntegerField(allow_null=True, help_text="Bytes read from storage (scan-side).")
    rows_returned = serializers.IntegerField(help_text="Rows in the `result` payload.")


# `test_read` is a deliberately non-standard action verb. This scope is only
# ever minted programmatically (see `run_autoresearch_smoke.py`) and handed to
# the autoresearch sandbox so it can call this endpoint. It's never exposed in
# the personal-API-key / OAuth-consent UI — that UI only knows `:read` / `:write`.
# A regular end user can't mint this scope from the UI, which is the intent:
# the proxy exists for the autoresearch system to talk to itself, not for
# human operators.
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
# Waiters time out slightly above the server-side cap so a stuck query can't
# pile callers up indefinitely — they get a 503 and can retry.
_LOCK_WAIT_TIMEOUT_SECONDS = MAX_EXECUTION_TIME_SECONDS + 10  # 310s
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

    @extend_schema(
        request=ExecuteRequestSerializer,
        responses={200: ExecuteResponseSerializer},
        summary="Run a read-only query against the autoresearch test cluster",
        description=(
            "DEBUG-only proxy that forwards SQL to the ClickHouse `autoresearch` user. "
            "SQL safety comes entirely from the CH user's grants + readonly=2 profile; "
            "the endpoint does not parse or filter SQL."
        ),
    )
    @action(detail=False, methods=["POST"], url_path="execute-test")
    def execute_test(self, request: Request) -> Response:
        if not settings.DEBUG or settings.CLOUD_DEPLOYMENT in _PRODUCTION_CLOUD_DEPLOYMENTS:
            return Response(
                {"error": "query_performance_proxy is only available in DEBUG mode outside cloud deployments"},
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


# -------------------------------------------------------- canonicalization --
#
# `clickhouse-driver` returns rows as Python tuples of native types (Decimal,
# datetime, UUID, tuple, bytes, IPvXAddress, ...). We serialize each value to
# a deterministic string that matches ClickHouse's own ``FORMAT JSONEachRow``
# output, so the comparison oracle (ch_compare_results.py) can diff results
# coming from two different transports without being tricked by incidental
# encoding differences. Without this, a candidate that returns
# ``Decimal("1.10")`` vs a baseline with ``Decimal("1.1")`` would be reported
# as mismatched even though the underlying values are equal.


def _canonicalize_value(v: object) -> object:
    if v is None:
        return None
    if isinstance(v, bool):
        # Note: bool is a subclass of int — must branch first.
        return v
    if isinstance(v, int | float | str):
        return v
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime):
        # CH's JSONEachRow uses ``YYYY-MM-DD hh:mm:ss[.ffffff]`` (space, not
        # T; no timezone suffix). Normalize any aware datetime to UTC first.
        if v.tzinfo is not None:
            v = v.astimezone(UTC).replace(tzinfo=None)
        if v.microsecond:
            return v.strftime("%Y-%m-%d %H:%M:%S.%f")
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, IPv4Address | IPv6Address):
        return str(v)
    if isinstance(v, bytes):
        # CH String columns surface as bytes in the native driver; JSONEachRow
        # emits them as strings with invalid-UTF8 bytes escaped. ``replace``
        # matches that behavior without raising.
        return v.decode("utf-8", errors="replace")
    if isinstance(v, tuple | list):
        return [_canonicalize_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _canonicalize_value(x) for k, x in v.items()}
    return v


def _canonicalize_rows(rows: object) -> list[list[object]]:
    if not isinstance(rows, list):
        return []
    return [[_canonicalize_value(v) for v in row] for row in rows]


# ---------------------------------------------------------------- execution --


def _run_autoresearch_query(sql: str) -> Response:
    # Single global lock: protects `SyncClient` mutable state AND enforces the
    # single-tenant test cluster's "one query at a time" invariant. Autoresearch
    # runs one campaign at a time so genuine contention is rare; a stuck query
    # (up to MAX_EXECUTION_TIME_SECONDS) shouldn't hold a waiter longer than
    # that, so we time out at +10s and 503 rather than letting callers queue up.
    acquired = _QUERY_LOCK.acquire(timeout=_LOCK_WAIT_TIMEOUT_SECONDS)
    if not acquired:
        return Response(
            {"error": "query_performance_proxy is busy; retry shortly"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    try:
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
    finally:
        _QUERY_LOCK.release()

    canonical_rows = _canonicalize_rows(rows)
    return Response(
        {
            "result": canonical_rows,
            "query_id": query_id,
            "elapsed_ms": round(elapsed_seconds * 1000.0, 3) if isinstance(elapsed_seconds, int | float) else None,
            "rows_read": getattr(profile_info, "rows", None),
            "bytes_read": getattr(profile_info, "bytes", None),
            "rows_returned": len(canonical_rows),
        },
        status=status.HTTP_200_OK,
    )
