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
import time
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


# Single-tenant cluster, so only duration matters — any memory/row/byte cap
# low enough to protect anything would abort legitimate exploration queries
# and slow the campaign.
MAX_EXECUTION_TIME_SECONDS = 5 * 60


class ExecuteRequestSerializer(serializers.Serializer):
    sql = serializers.CharField()


_ACTION_SCOPES: dict[str, list[str]] = {
    "execute_test": ["clickhouse_test_cluster_perf:test_read"],
}

_QUERY_SETTINGS: dict[str, object] = {
    "max_execution_time": MAX_EXECUTION_TIME_SECONDS,
    "readonly": 2,
    "log_comment": json.dumps({"kind": "query_performance_autoresearch_proxy"}),
}


class QueryPerformanceProxyViewSet(viewsets.ViewSet):
    authentication_classes = [OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "INTERNAL"

    # Not project-nested: no URL team to validate scoped_teams against. Access
    # is gated by clickhouse_test_cluster_perf:test_read + DEBUG + the CH user's profile.
    skip_scoped_team_enforcement = True

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
    client = SyncClient(
        host=settings.CLICKHOUSE_TEST_CLUSTER_HOST,
        database=settings.CLICKHOUSE_TEST_CLUSTER_DATABASE,
        user=settings.CLICKHOUSE_TEST_CLUSTER_USER,
        password=settings.CLICKHOUSE_TEST_CLUSTER_PASSWORD,
        secure=settings.CLICKHOUSE_TEST_CLUSTER_SECURE,
        ca_certs=settings.CLICKHOUSE_TEST_CLUSTER_CA,
        verify=settings.CLICKHOUSE_TEST_CLUSTER_VERIFY,
    )
    start = time.monotonic()
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
    elapsed_ms = (time.monotonic() - start) * 1000.0

    profile_info = getattr(client.last_query, "profile_info", None)

    return Response(
        {
            "result": rows if isinstance(rows, list) else [],
            "elapsed_ms": round(elapsed_ms, 3),
            "rows_read": getattr(profile_info, "rows", None),
            "bytes_read": getattr(profile_info, "bytes", None),
            "rows_returned": len(rows) if isinstance(rows, list) else None,
        },
        status=status.HTTP_200_OK,
    )
