import time
import collections
from dataclasses import dataclass
from typing import Any

import psycopg
import structlog
from psycopg.adapt import Loader
from psycopg.rows import dict_row

logger = structlog.get_logger(__name__)

DEFAULT_QUERY_TIMEOUT_SECONDS = 30


@dataclass
class QueryResult:
    columns: list[str]
    types: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    execution_time_ms: float
    error: str | None = None


@dataclass
class SchemaInfo:
    tables: dict[str, list[tuple[str, str]]]  # table_name -> [(column_name, data_type)]


class JsonAsStringLoader(Loader):
    def load(self, data):
        if data is None:
            return None
        return bytes(data).decode("utf-8")


class RangeAsStringLoader(Loader):
    """Load PostgreSQL range types as their string representation."""

    def load(self, data):
        if data is None:
            return None
        return bytes(data).decode("utf-8")


class DirectQueryExecutor:
    """Executes SQL queries directly against external databases.

    Currently supports PostgreSQL. Used for query-only data sources where
    data is not synced to PostHog but queried directly.
    """

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        schema: str = "public",
        ssh_tunnel: dict | None = None,
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.schema = schema
        self.ssh_tunnel = ssh_tunnel

    def _get_connection(self) -> psycopg.Connection:
        """Create a connection to the database."""
        # TODO: Add SSH tunnel support if ssh_tunnel is configured
        connection = psycopg.connect(
            host=self.host,
            port=self.port,
            dbname=self.database,
            user=self.user,
            password=self.password,
            sslmode="prefer",
            connect_timeout=15,
            sslrootcert="/tmp/no.txt",
            sslcert="/tmp/no.txt",
            sslkey="/tmp/no.txt",
        )

        # Register type loaders for JSON and range types
        connection.adapters.register_loader("jsonb", JsonAsStringLoader)
        connection.adapters.register_loader("json", JsonAsStringLoader)

        for range_type in [
            "int4range",
            "int8range",
            "numrange",
            "daterange",
            "tsrange",
            "tstzrange",
            "int4multirange",
            "int8multirange",
            "nummultirange",
            "datemultirange",
            "tsmultirange",
            "tstzmultirange",
        ]:
            connection.adapters.register_loader(range_type, RangeAsStringLoader)

        return connection

    def execute_query(
        self, sql: str, max_rows: int = 1000, timeout_seconds: int = DEFAULT_QUERY_TIMEOUT_SECONDS
    ) -> QueryResult:
        """Execute a SQL query and return results.

        Args:
            sql: The SQL query to execute
            max_rows: Maximum number of rows to return (default 1000)
            timeout_seconds: Query timeout in seconds (default 30)

        Returns:
            QueryResult with columns, rows, execution time, and any errors
        """
        start_time = time.time()

        logger.info(
            "direct_query_execute_start",
            database=self.database,
            schema=self.schema,
            max_rows=max_rows,
            timeout_seconds=timeout_seconds,
        )

        try:
            connection = self._get_connection()

            with connection.cursor(row_factory=dict_row) as cursor:
                # Set query timeout and read-only mode for safety
                cursor.execute(f"SET statement_timeout = '{timeout_seconds}s'")
                cursor.execute("SET default_transaction_read_only = ON")

                cursor.execute(sql)

                # Get column names and types from description
                columns = [desc.name for desc in cursor.description] if cursor.description else []
                # type_code is the OID of the type, we convert to string representation
                types = [str(desc.type_code) for desc in cursor.description] if cursor.description else []

                # Fetch rows up to max_rows
                rows = cursor.fetchmany(max_rows)
                row_count = len(rows)

                # Convert any non-serializable types to strings
                serializable_rows = []
                for row in rows:
                    serializable_row = {}
                    for key, value in row.items():
                        if isinstance(value, dict | list | str | int | float | bool | type(None)):
                            serializable_row[key] = value
                        else:
                            serializable_row[key] = str(value)
                    serializable_rows.append(serializable_row)

            connection.close()

            execution_time_ms = (time.time() - start_time) * 1000

            logger.info(
                "direct_query_execute_success",
                database=self.database,
                schema=self.schema,
                row_count=row_count,
                execution_time_ms=execution_time_ms,
            )

            return QueryResult(
                columns=columns,
                types=types,
                rows=serializable_rows,
                row_count=row_count,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000

            # Sanitize error message to avoid leaking sensitive information
            error_message = str(e)
            if "password" in error_message.lower():
                error_message = "Connection failed. Please check your credentials."
            elif "timeout" in error_message.lower():
                error_message = f"Query timed out after {timeout_seconds} seconds."

            logger.warning(
                "direct_query_execute_error",
                database=self.database,
                schema=self.schema,
                execution_time_ms=execution_time_ms,
                error=str(e),
            )

            return QueryResult(
                columns=[],
                types=[],
                rows=[],
                row_count=0,
                execution_time_ms=execution_time_ms,
                error=error_message,
            )

    def get_schema(self) -> SchemaInfo:
        """Get schema information (tables and columns) from the database.

        Reuses the pattern from the existing get_schemas() function.
        """
        try:
            connection = self._get_connection()

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM (
                        SELECT table_name, column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = %(schema)s
                        UNION ALL
                        SELECT c.relname AS table_name, a.attname AS column_name,
                               pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type
                        FROM pg_class c
                        JOIN pg_namespace n ON c.relnamespace = n.oid
                        JOIN pg_attribute a ON a.attrelid = c.oid
                        WHERE c.relkind = 'm' AND n.nspname = %(schema)s
                        AND a.attnum > 0 AND NOT a.attisdropped
                    ) t
                    ORDER BY table_name ASC
                    """,
                    {"schema": self.schema},
                )
                result = cursor.fetchall()

                tables: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
                for row in result:
                    table_name, column_name, data_type = row
                    tables[table_name].append((column_name, data_type))

            connection.close()

            return SchemaInfo(tables=dict(tables))

        except Exception as e:
            raise RuntimeError(f"Failed to get schema: {e}") from e

    def validate_connection(self) -> tuple[bool, str | None]:
        """Test the database connection.

        Returns:
            Tuple of (success, error_message)
        """
        try:
            connection = self._get_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            connection.close()
            return True, None
        except Exception as e:
            return False, str(e)

    @classmethod
    def from_source(cls, source) -> "DirectQueryExecutor":
        """Create a DirectQueryExecutor from an ExternalDataSource model instance.

        Args:
            source: ExternalDataSource model instance with job_inputs containing
                   host, port, database, user, password, schema

        Returns:
            Configured DirectQueryExecutor instance
        """
        job_inputs = source.job_inputs or {}

        return cls(
            host=job_inputs.get("host", ""),
            port=int(job_inputs.get("port", 5432)),
            database=job_inputs.get("database", ""),
            user=job_inputs.get("user", ""),
            password=job_inputs.get("password", ""),
            schema=job_inputs.get("schema", "public"),
            ssh_tunnel=job_inputs.get("ssh_tunnel"),
        )
