from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.data_warehouse.backend.models import ExternalDataSource
from products.data_warehouse.backend.services import DirectQueryExecutor


class DirectQueryViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """API for executing SQL queries directly against external databases.

    This is used for query-only data sources where data is not synced to PostHog
    but queried directly from the source database.
    """

    scope_object = "INTERNAL"

    @action(detail=False, methods=["POST"], url_path="execute")
    def execute(self, request: Request, *args, **kwargs) -> Response:
        """Execute a SQL query against a query-only data source.

        Request body:
            - source_id: ID of the query-only data source
            - sql: SQL query to execute
            - max_rows: Maximum number of rows to return (default 1000)

        Returns:
            - columns: List of column names
            - rows: List of row dictionaries
            - row_count: Number of rows returned
            - execution_time_ms: Query execution time in milliseconds
            - error: Error message if query failed
        """
        source_id = request.data.get("source_id")
        sql = request.data.get("sql")
        max_rows = request.data.get("max_rows", 1000)

        if not source_id:
            return Response(
                {"error": "source_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not sql:
            return Response(
                {"error": "sql is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            source = ExternalDataSource.objects.get(
                pk=source_id,
                team_id=self.team_id,
                query_only=True,
            )
        except ExternalDataSource.DoesNotExist:
            return Response(
                {"error": "Query-only source not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        executor = DirectQueryExecutor.from_source(source)
        result = executor.execute_query(sql, max_rows=max_rows)

        if result.error:
            return Response(
                {
                    "error": result.error,
                    "execution_time_ms": result.execution_time_ms,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
                "execution_time_ms": result.execution_time_ms,
            }
        )

    @action(detail=False, methods=["GET"], url_path="sources")
    def list_sources(self, request: Request, *args, **kwargs) -> Response:
        """List all query-only data sources for the current team."""
        sources = ExternalDataSource.objects.filter(
            team_id=self.team_id,
            query_only=True,
        ).values("id", "source_type", "prefix", "created_at", "status")

        return Response({"sources": list(sources)})

    @action(detail=False, methods=["GET"], url_path="schema/(?P<source_id>[^/.]+)")
    def get_schema(self, request: Request, source_id: str, *args, **kwargs) -> Response:
        """Get schema information for a query-only data source.

        Returns:
            - tables: Dictionary mapping table names to lists of (column_name, data_type) tuples
        """
        try:
            source = ExternalDataSource.objects.get(
                pk=source_id,
                team_id=self.team_id,
                query_only=True,
            )
        except ExternalDataSource.DoesNotExist:
            return Response(
                {"error": "Query-only source not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        executor = DirectQueryExecutor.from_source(source)

        try:
            schema_info = executor.get_schema()
            return Response({"tables": schema_info.tables})
        except RuntimeError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
