import time
from typing import Any, Optional

import snowflake.connector
from snowflake.connector import DictCursor, ProgrammingError
import structlog

from posthog.warehouse.connectors.base import (
    BaseWarehouseConnector,
    ColumnSchema,
    PushDownCapabilities,
    QueryCost,
    QueryResult,
    TableSchema,
)

logger = structlog.get_logger(__name__)


class SnowflakeConnector(BaseWarehouseConnector):
    """Snowflake connector for direct querying"""

    def __init__(self, credentials: dict[str, Any], config: dict[str, Any]):
        super().__init__(credentials, config)

        required_fields = ["account", "username", "password"]
        missing_fields = [field for field in required_fields if not credentials.get(field)]
        if missing_fields:
            raise ValueError(f"Snowflake credentials missing required fields: {', '.join(missing_fields)}")

        self.account = credentials["account"]
        self.username = credentials["username"]
        self.password = credentials["password"]
        self.warehouse = credentials.get("warehouse")
        self.database = credentials.get("database")
        self.schema = credentials.get("schema")
        self.role = credentials.get("role")

        try:
            self.conn = snowflake.connector.connect(
                user=self.username,
                password=self.password,
                account=self.account,
                warehouse=self.warehouse,
                database=self.database,
                schema=self.schema,
                role=self.role,
                network_timeout=self.get_timeout(),
                client_session_keep_alive=True,
            )
            logger.info("Snowflake connection established")
        except Exception as e:
            logger.error(f"Failed to connect to Snowflake: {e}")
            raise ValueError(f"Invalid Snowflake credentials: {e}")

    def execute_query(
        self, sql: str, params: Optional[dict[str, Any]] = None
    ) -> QueryResult:
        """Execute SQL query on Snowflake"""
        cursor = self.conn.cursor(DictCursor)
        start_time = time.time()

        try:
            cursor.execute(sql, params or {})
            rows = cursor.fetchall()

            execution_time_ms = int((time.time() - start_time) * 1000)

            columns = [desc[0] for desc in cursor.description] if cursor.description else []

            bytes_processed = 0
            if hasattr(cursor, "_sfqid") and cursor._sfqid:
                try:
                    stats_cursor = self.conn.cursor()
                    stats_cursor.execute(
                        f"SELECT BYTES_SCANNED FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY()) WHERE QUERY_ID = '{cursor._sfqid}'"
                    )
                    stats_result = stats_cursor.fetchone()
                    if stats_result and stats_result[0]:
                        bytes_processed = int(stats_result[0])
                    stats_cursor.close()
                except Exception as e:
                    logger.warning(f"Could not get bytes scanned: {e}")

            logger.info(
                f"Snowflake query executed successfully",
                execution_time_ms=execution_time_ms,
                bytes_processed=bytes_processed,
                row_count=len(rows),
            )

            return QueryResult(
                rows=rows,
                columns=columns,
                execution_time_ms=execution_time_ms,
                bytes_processed=bytes_processed,
                cached=False,
            )

        except ProgrammingError as e:
            logger.error(f"Snowflake query failed: {e}")
            raise Exception(f"Snowflake query failed: {e}")
        finally:
            cursor.close()

    def get_schema(self, schema_name: Optional[str] = None) -> list[TableSchema]:
        """Retrieve available tables and columns from Snowflake schema"""
        schema = schema_name or self.schema

        if not schema:
            raise ValueError(
                "Schema name must be provided either in schema_name parameter or in credentials"
            )

        if not self.database:
            raise ValueError("Database must be specified in credentials to retrieve schema")

        cursor = self.conn.cursor()
        schemas: list[TableSchema] = []

        try:
            cursor.execute(f"SHOW TABLES IN SCHEMA {self.database}.{schema}")
            tables = cursor.fetchall()

            for table_row in tables:
                table_name = table_row[1]

                cursor.execute(f"DESCRIBE TABLE {self.database}.{schema}.{table_name}")
                columns_info = cursor.fetchall()

                columns = [
                    ColumnSchema(
                        name=col[0],
                        type=col[1],
                        nullable=col[3] == "Y",
                    )
                    for col in columns_info
                ]

                cursor.execute(
                    f"SELECT ROW_COUNT, BYTES FROM {self.database}.INFORMATION_SCHEMA.TABLES "
                    f"WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table_name}'"
                )
                stats = cursor.fetchone()
                row_count = stats[0] if stats and stats[0] else None
                size_bytes = stats[1] if stats and stats[1] else None

                schemas.append(
                    TableSchema(
                        name=f"{schema}.{table_name}",
                        columns=columns,
                        row_count=row_count,
                        size_bytes=size_bytes,
                    )
                )

            logger.info(
                f"Retrieved schema for Snowflake",
                database=self.database,
                schema=schema,
                table_count=len(schemas),
            )

            return schemas

        except ProgrammingError as e:
            logger.error(f"Failed to get Snowflake schema: {e}")
            raise Exception(f"Failed to get Snowflake schema: {e}")
        finally:
            cursor.close()

    def estimate_cost(self, sql: str) -> QueryCost:
        """Estimate query cost for Snowflake

        Note: Snowflake doesn't provide easy cost estimation without EXPLAIN,
        which returns execution plan rather than cost. We return a message
        indicating this limitation.
        """
        cursor = self.conn.cursor()

        try:
            cursor.execute(f"EXPLAIN {sql}")
            plan_rows = cursor.fetchall()

            logger.info(f"Snowflake query plan retrieved", plan_rows=len(plan_rows))

            return QueryCost(
                estimated_bytes=0,
                estimated_cost_usd=0.0,
                warning_message=(
                    "Cost estimation not available for Snowflake. "
                    "Snowflake charges based on compute credits consumed. "
                    "Actual costs depend on warehouse size and query complexity."
                ),
            )

        except Exception as e:
            logger.warning(f"Could not get Snowflake query plan: {e}")
            return QueryCost(
                estimated_bytes=0,
                estimated_cost_usd=0.0,
                warning_message="Cost estimation not available for Snowflake",
            )
        finally:
            cursor.close()

    def test_connection(self) -> bool:
        """Test if Snowflake connection credentials are valid"""
        cursor = self.conn.cursor()

        try:
            cursor.execute("SELECT 1 as test")
            result = cursor.fetchone()

            if result and result[0] == 1:
                logger.info("Snowflake connection test successful")
                return True
            else:
                logger.error("Snowflake connection test returned unexpected result")
                return False

        except Exception as e:
            logger.error(f"Snowflake connection test failed: {e}")
            return False
        finally:
            cursor.close()

    def supports_push_down(self) -> PushDownCapabilities:
        """Snowflake supports most push-down optimizations"""
        return PushDownCapabilities(
            supports_predicate=True,
            supports_projection=True,
            supports_aggregation=True,
            supports_limit=True,
            supports_join=True,
        )

    def close(self) -> None:
        """Close Snowflake connection"""
        if hasattr(self, "conn") and self.conn:
            self.conn.close()
            logger.info("Snowflake connection closed")
