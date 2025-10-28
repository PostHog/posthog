"""Simple query executor for direct warehouse queries

This module provides utilities for executing queries on warehouse tables
that have a direct warehouse connection (mode='direct').
"""

import structlog
from typing import Any

from posthog.warehouse.models.connection import WarehouseConnection
from posthog.warehouse.models.table import DataWarehouseTable

logger = structlog.get_logger(__name__)


class WarehouseQueryExecutor:
    """Execute queries on warehouse tables with direct connections"""

    def __init__(self, table: DataWarehouseTable):
        """Initialize executor for a specific warehouse table

        Args:
            table: DataWarehouseTable with a warehouse_connection set
        """
        if not hasattr(table, 'warehouse_connection') or not table.warehouse_connection:
            raise ValueError("Table must have a warehouse_connection for direct query execution")

        self.table = table
        self.connection = table.warehouse_connection

    def execute_query(self, sql: str) -> dict[str, Any]:
        """Execute SQL query on the warehouse

        Args:
            sql: SQL query string to execute

        Returns:
            Dictionary containing:
            - results: List of row dictionaries
            - columns: List of column names
            - types: List of column types (optional)
            - metadata: Execution metadata (time, bytes, etc.)
        """
        logger.info(
            "Executing warehouse query",
            table_name=self.table.name,
            connection_id=self.connection.id,
            connection_name=self.connection.name,
            provider=self.connection.provider,
            team_id=self.table.team_id,
        )

        try:
            connector = self.connection.get_connector()
            result = connector.execute_query(sql)
            connector.close()

            logger.info(
                "Warehouse query completed successfully",
                table_name=self.table.name,
                connection_id=self.connection.id,
                execution_time_ms=result.execution_time_ms,
                row_count=len(result.rows),
                bytes_processed=result.bytes_processed,
            )

            return {
                "results": result.rows,
                "columns": result.columns,
                "types": [],  # Could map warehouse types to HogQL types
                "metadata": {
                    "execution_time_ms": result.execution_time_ms,
                    "bytes_processed": result.bytes_processed,
                    "cached": result.cached,
                    "source": "warehouse",
                    "provider": self.connection.provider,
                    "connection_name": self.connection.name,
                },
            }

        except Exception as e:
            logger.error(
                "Warehouse query failed",
                table_name=self.table.name,
                connection_id=self.connection.id,
                error=str(e),
                exc_info=True,
            )
            raise


def is_warehouse_direct_table(table: DataWarehouseTable) -> bool:
    """Check if a table uses direct warehouse connection

    Args:
        table: DataWarehouseTable to check

    Returns:
        True if table has a warehouse_connection in direct mode
    """
    if not hasattr(table, 'warehouse_connection'):
        return False

    if not table.warehouse_connection:
        return False

    return table.warehouse_connection.mode == WarehouseConnection.MODE_DIRECT


def execute_warehouse_query(table: DataWarehouseTable, sql: str) -> dict[str, Any]:
    """Execute a query on a warehouse table

    Convenience function that creates an executor and runs the query.

    Args:
        table: DataWarehouseTable with warehouse_connection
        sql: SQL query to execute

    Returns:
        Query results dictionary

    Raises:
        ValueError: If table doesn't have a warehouse_connection
        Exception: If query execution fails
    """
    executor = WarehouseQueryExecutor(table)
    return executor.execute_query(sql)
