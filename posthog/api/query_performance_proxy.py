"""OAuth-gated ClickHouse proxy for query-performance autoresearch.

* Runs queries on the test cluster
* Requires DEBUG=1 for now (i.e. is disabled in prod)
* Requires a `CLICKHOUSE_TEST_CLUSTER_HOST` env variable
* The test cluster must only contain data we are willing to point an autoresearch LLM at
    * For now this is only our own (team 2) data
* Requires ``scope_object = "INTERNAL"`` plus explicit OAuth scope ``clickhouse_perf:test_read``
  * a token with this scope is created for autoresearch sandboxes
* Add ``settings={"max_execution_time": 60, "readonly": 2}``
    * In the future, will also set a test cluster user, this is not needed while DEBUG=1 is enforced
* Don't try to validate the SQL, we are protected by the nature of how limited the data on the test cluster is
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


class ExecuteRequestSerializer(serializers.Serializer):
    sql = serializers.CharField()


_ACTION_SCOPES: dict[str, list[str]] = {
    "execute_test": ["clickhouse_perf:test_read"],
}

_QUERY_SETTINGS: dict[str, object] = {
    "max_execution_time": 60,
    "readonly": 2,
    "log_comment": json.dumps({"kind": "query_performance_autoresearch_proxy"}),
}


class QueryPerformanceProxyViewSet(viewsets.ViewSet):
    authentication_classes = [OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "INTERNAL"

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        """
        Scope dispatch goes through :meth:`dangerously_get_required_scopes` so the
        action keeps its own scope without pulling in ``TeamAndOrgViewSetMixin``
        (which is designed for team-nested routes). ``scope_object = "INTERNAL"``
        still signals to ``ScopeBasePermission`` that the usual CRUD-derived
        default doesn't apply.
        """
        return _ACTION_SCOPES.get(getattr(view, "action", "") or "")

    @action(detail=False, methods=["POST"], url_path="execute-test")
    def execute_test(self, request: Request) -> Response:
        # Dev-only for now
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
        # sync_execute in DEBUG mode refuses untagged queries (see
        # posthog.clickhouse.client.execute.sync_execute). This isn't a
        # customer-facing query — it's an autoresearch passthrough — so tag
        # it as an internal query. Without this the call raises
        # UntaggedQueryError, which the generic except below would disguise
        # as "clickhouse unreachable".
        with tags_context(product=Product.INTERNAL, feature=Feature.QUERY):
            rows = sync_execute(sql, settings=_QUERY_SETTINGS, sync_client=client, readonly=True, flush=False)
    except InternalCHQueryError as e:
        # Log the full exception (stack trace + message) server-side so
        # operators can debug. The response only carries the ClickHouse
        # error code — CodeQL flags returning the exception text as
        # information exposure, and the agent can look up what a given
        # code means without needing the raw message echoed back.
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

    return Response(
        {
            "result": rows if isinstance(rows, list) else [],
            "elapsed_ms": round(elapsed_ms, 3),
            "rows_read": len(rows) if isinstance(rows, list) else None,
            "bytes_read": None,
            "query_id": None,
        },
        status=status.HTTP_200_OK,
    )


