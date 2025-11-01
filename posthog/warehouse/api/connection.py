from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
import structlog

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.warehouse.models.connection import WarehouseConnection

logger = structlog.get_logger(__name__)


class WarehouseConnectionSerializer(serializers.ModelSerializer):
    """Serializer for warehouse connections

    Important: credentials are write-only for security.
    They are encrypted at rest and never exposed in API responses.
    """

    class Meta:
        model = WarehouseConnection
        fields = [
            "id",
            "created_at",
            "updated_at",
            "created_by",
            "name",
            "provider",
            "credentials",
            "mode",
            "is_active",
            "config",
            "last_tested_at",
            "last_test_status",
            "last_test_error",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "created_by",
            "last_tested_at",
            "last_test_status",
            "last_test_error",
        ]
        extra_kwargs = {
            "credentials": {
                "write_only": True,
                "help_text": "Encrypted credentials for warehouse connection. Never returned in responses.",
            }
        }

    def to_representation(self, instance):
        """Remove sensitive fields from response"""
        representation = super().to_representation(instance)

        # Never expose credentials in API responses
        if "credentials" in representation:
            del representation["credentials"]

        # Add connection health status
        representation["connection_status"] = (
            "healthy" if instance.last_test_status and instance.is_active else "unhealthy"
        )

        return representation

    def create(self, validated_data):
        # Set created_by to current user
        validated_data["created_by"] = self.context["request"].user
        validated_data["team"] = self.context["team"]
        return super().create(validated_data)


class WarehouseConnectionViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """API endpoints for managing warehouse connections

    Warehouse connections allow PostHog to query external data warehouses
    like BigQuery, Snowflake, Redshift, and Databricks directly without
    syncing data to S3/ClickHouse.

    Endpoints:
    - GET /api/environments/:team_id/warehouse_connections/ - List connections
    - POST /api/environments/:team_id/warehouse_connections/ - Create connection
    - GET /api/environments/:team_id/warehouse_connections/:id/ - Get connection details
    - PATCH /api/environments/:team_id/warehouse_connections/:id/ - Update connection
    - DELETE /api/environments/:team_id/warehouse_connections/:id/ - Delete connection
    - POST /api/environments/:team_id/warehouse_connections/test/ - Test connection before saving
    - POST /api/environments/:team_id/warehouse_connections/:id/test/ - Test existing connection
    - GET /api/environments/:team_id/warehouse_connections/:id/schema/ - Get warehouse schema
    - POST /api/environments/:team_id/warehouse_connections/:id/estimate_cost/ - Estimate query cost
    """

    queryset = WarehouseConnection.objects.all()
    serializer_class = WarehouseConnectionSerializer

    def get_queryset(self):
        """Filter connections by team"""
        return super().get_queryset().filter(team=self.team).order_by("-created_at")

    @action(detail=False, methods=["post"])
    def test(self, request: Request) -> Response:
        """Test connection before saving

        Allows users to validate credentials before creating a connection.
        Does not save anything to the database.

        Example request body:
        {
            "name": "My BigQuery",
            "provider": "bigquery",
            "credentials": {
                "project_id": "my-project",
                "service_account_json": {...}
            },
            "mode": "direct"
        }

        Returns:
        {
            "status": "success" | "error",
            "message": "Connection successful" | error_message
        }
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Create temporary connection (don't save)
        connection = WarehouseConnection(**serializer.validated_data)
        connection.team = self.team

        logger.info(
            "Testing warehouse connection",
            team_id=self.team.id,
            provider=connection.provider,
            mode=connection.mode,
        )

        success, error_message = connection.test_connection(save_result=False)

        if success:
            return Response(
                {"status": "success", "message": "Connection successful"}, status=status.HTTP_200_OK
            )
        else:
            # Expose only generic error message to user, log the detailed error server-side
            return Response(
                {"status": "error", "message": "Connection failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def test_connection(self, request: Request, pk=None) -> Response:
        """Test existing connection

        Re-tests an existing connection and updates the last_tested_at,
        last_test_status, and last_test_error fields.

        Returns:
        {
            "status": "success" | "error",
            "message": "Connection successful" | error_message,
            "last_tested_at": "2024-10-28T12:34:56Z",
            "last_test_status": true | false
        }
        """
        connection = self.get_object()

        logger.info(
            "Testing existing warehouse connection",
            connection_id=connection.id,
            connection_name=connection.name,
            team_id=self.team.id,
        )

        success, error_message = connection.test_connection(save_result=True)

        if success:
            return Response(
                {
                    "status": "success",
                    "message": "Connection successful",
                    "last_tested_at": connection.last_tested_at,
                    "last_test_status": connection.last_test_status,
                },
                status=status.HTTP_200_OK,
            )
        else:
            return Response(
                {
                    "status": "error",
                    "message": "Connection failed",
                    "last_tested_at": connection.last_tested_at,
                    "last_test_status": connection.last_test_status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["get"])
    def schema(self, request: Request, pk=None) -> Response:
        """Get warehouse schema (tables and columns)

        Retrieves available tables and their columns from the connected warehouse.
        Useful for building query builders and table browsers.

        Query parameters:
        - schema_name (optional): Filter to specific schema/dataset

        Returns:
        {
            "tables": [
                {
                    "name": "my_dataset.my_table",
                    "columns": [
                        {"name": "id", "type": "INTEGER", "nullable": false},
                        {"name": "name", "type": "STRING", "nullable": true}
                    ],
                    "row_count": 1000,
                    "size_bytes": 50000
                }
            ]
        }
        """
        connection = self.get_object()
        schema_name = request.query_params.get("schema_name")

        logger.info(
            "Fetching warehouse schema",
            connection_id=connection.id,
            connection_name=connection.name,
            schema_name=schema_name,
            team_id=self.team.id,
        )

        try:
            connector = connection.get_connector()
            schema = connector.get_schema(schema_name=schema_name)
            connector.close()

            # Convert to dict format for JSON response
            tables_data = [
                {
                    "name": table.name,
                    "columns": [
                        {"name": col.name, "type": col.type, "nullable": col.nullable} for col in table.columns
                    ],
                    "row_count": table.row_count,
                    "size_bytes": table.size_bytes,
                }
                for table in schema
            ]

            logger.info(
                "Successfully fetched warehouse schema",
                connection_id=connection.id,
                table_count=len(tables_data),
            )

            return Response({"tables": tables_data}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(
                "Failed to fetch warehouse schema",
                connection_id=connection.id,
                error=str(e),
                exc_info=True,
            )
            return Response(
                {"error": "Failed to fetch schema"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["post"])
    def estimate_cost(self, request: Request, pk=None) -> Response:
        """Estimate cost for a warehouse query

        Useful for warning users before executing expensive queries.
        Cost estimation accuracy varies by warehouse provider:
        - BigQuery: Accurate (uses dry-run API)
        - Snowflake: Not available (returns message)
        - Redshift: Not available
        - Databricks: Not available

        Request body:
        {
            "sql": "SELECT * FROM large_table WHERE date > '2024-01-01'"
        }

        Returns:
        {
            "estimated_bytes": 1000000000,
            "estimated_cost_usd": 0.05,
            "warning_message": "This query will scan 1.00 GB (estimated cost: $0.05)"
        }
        """
        connection = self.get_object()
        sql = request.data.get("sql")

        if not sql:
            return Response({"error": "SQL query required"}, status=status.HTTP_400_BAD_REQUEST)

        logger.info(
            "Estimating warehouse query cost",
            connection_id=connection.id,
            connection_name=connection.name,
            team_id=self.team.id,
            sql_preview=sql[:100],
        )

        try:
            connector = connection.get_connector()
            cost = connector.estimate_cost(sql)
            connector.close()

            logger.info(
                "Cost estimation completed",
                connection_id=connection.id,
                estimated_bytes=cost.estimated_bytes,
                estimated_cost_usd=cost.estimated_cost_usd,
            )

            return Response(
                {
                    "estimated_bytes": cost.estimated_bytes,
                    "estimated_cost_usd": cost.estimated_cost_usd,
                    "warning_message": cost.warning_message,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(
                "Failed to estimate query cost",
                connection_id=connection.id,
                error=str(e),
                exc_info=True,
            )
            return Response(
                {"error": "Failed to estimate cost"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
