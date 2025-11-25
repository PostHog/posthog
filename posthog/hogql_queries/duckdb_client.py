from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class DuckDBClient:
    """
    Simple DuckDB client for executing queries against the data warehouse.
    This client initializes a DuckDB connection and executes SQL queries.
    """

    def __init__(self):
        self._connection = None

    def _get_connection(self):
        """
        Get or create a DuckDB connection.
        Lazily initializes the connection on first use.
        """
        if self._connection is None:
            try:
                import duckdb

                self._connection = duckdb.connect()
                logger.info("duckdb_connection_initialized")
            except ImportError:
                raise ImportError("duckdb is not installed. Please install it with: pip install duckdb")
        return self._connection

    def execute(self, query: str, parameters: dict[str, Any] | None = None) -> tuple[list[list[Any]], list[str]]:
        """
        Execute a SQL query against DuckDB.

        Args:
            query: The SQL query to execute
            parameters: Optional dictionary of parameters to bind to the query

        Returns:
            A tuple of (results, columns) where results is a list of rows
            and columns is a list of column names
        """
        conn = self._get_connection()

        try:
            if parameters:
                result = conn.execute(query, parameters)
            else:
                result = conn.execute(query)

            columns = [desc[0] for desc in result.description] if result.description else []
            rows = result.fetchall()

            return [list(row) for row in rows], columns
        except Exception:
            logger.exception("duckdb_query_error", query=query[:200])
            raise

    def close(self):
        """Close the DuckDB connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def get_duckdb_client() -> DuckDBClient:
    """
    Factory function to get a DuckDB client instance.
    Returns a new client instance for each call.
    """
    return DuckDBClient()
