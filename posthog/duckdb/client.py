from typing import Any


class DuckDBClient:
    """
    Simple DuckDB client for executing queries against the data warehouse.
    This client initializes a DuckDB connection and executes SQL queries.
    """

    def __init__(self):
        self._connection = None

    def _get_connection(self):
        if self._connection is None:
            try:
                import duckdb

                self._connection = duckdb.connect()
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
            raise

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def get_duckdb_client() -> DuckDBClient:
    return DuckDBClient()
