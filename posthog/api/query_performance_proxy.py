"""OAuth-gated ClickHouse passthrough for query-performance autoresearch.

Forwards SQL to the restricted ``autoresearch`` ClickHouse user on the test
cluster. Fails closed (503) when the cluster is not configured; never routes
to the main app ClickHouse.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.clickhouse.test_cluster_client import (
    TestClusterNotConfigured,
    TestClusterQueryError,
    execute_on_test_cluster,
)
from posthog.permissions import APIScopePermission

MAX_SQL_LENGTH = 64 * 1024


class ExecuteTestClusterRequestSerializer(serializers.Serializer):
    sql = serializers.CharField(max_length=MAX_SQL_LENGTH, help_text="ClickHouse SQL to run against the test cluster.")


class ExecuteTestClusterResponseSerializer(serializers.Serializer):
    result = serializers.ListField(
        child=serializers.ListField(),
        help_text="Rows returned, each as a positional list of canonicalized values.",
    )
    query_id = serializers.CharField(allow_null=True, help_text="ClickHouse query_id for this execution.")
    elapsed_ms = serializers.FloatField(allow_null=True, help_text="Server-side elapsed time in milliseconds.")
    rows_read = serializers.IntegerField(allow_null=True, help_text="Rows read from storage (scan-side).")
    bytes_read = serializers.IntegerField(allow_null=True, help_text="Bytes read from storage (scan-side).")
    rows_returned = serializers.IntegerField(help_text="Rows in the `result` payload.")


_ACTION_SCOPES: dict[str, list[str]] = {
    "execute_test": ["clickhouse_test_cluster_perf:read"],
}


class QueryPerformanceProxyViewSet(viewsets.ViewSet):
    authentication_classes = [OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "INTERNAL"

    # Not project- or org-nested. Opts out of `scoped_teams` / `scoped_organizations`
    # enforcement; see `APIScopePermission.check_team_and_org_permissions`.
    dangerously_skip_scoped_team_enforcement = True

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        return _ACTION_SCOPES.get(getattr(view, "action", "") or "")

    @extend_schema(
        request=ExecuteTestClusterRequestSerializer,
        responses={200: ExecuteTestClusterResponseSerializer},
        summary="Run a read-only query against the autoresearch test cluster",
        description=(
            "Forwards SQL to the restricted autoresearch ClickHouse user for query-performance "
            "analysis (query_log_archive and related tables). Read-only; row and time limited."
        ),
    )
    @action(detail=False, methods=["POST"], url_path="execute-test")
    def execute_test(self, request: Request) -> Response:
        serializer = ExecuteTestClusterRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            out = execute_on_test_cluster(serializer.validated_data["sql"])
        except TestClusterNotConfigured:
            return Response(
                {"detail": "Test cluster is not configured on this instance."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except TestClusterQueryError as err:
            return Response({"detail": str(err)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "result": out.result,
                "query_id": out.query_id,
                "elapsed_ms": out.elapsed_ms,
                "rows_read": out.rows_read,
                "bytes_read": out.bytes_read,
                "rows_returned": len(out.result),
            },
            status=status.HTTP_200_OK,
        )
