from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from posthog.warehouse.models.credential import DataWarehouseCredential


@dataclass
class QueryResult:
    """Result from executing a warehouse query"""

    rows: list[dict[str, Any]]
    columns: list[str]
    execution_time_ms: int
    bytes_processed: int
    cached: bool


@dataclass
class TableSchema:
    """Schema information for a warehouse table"""

    name: str
    columns: list["ColumnSchema"]
    row_count: Optional[int] = None
    size_bytes: Optional[int] = None


@dataclass
class ColumnSchema:
    """Schema information for a table column"""

    name: str
    type: str
    nullable: bool


@dataclass
class QueryCost:
    """Estimated cost for a query"""

    estimated_bytes: int
    estimated_cost_usd: float
    warning_message: Optional[str] = None


@dataclass
class PushDownCapabilities:
    """Capabilities that connector supports for optimization"""

    supports_predicate: bool = True
    supports_projection: bool = True
    supports_aggregation: bool = False
    supports_limit: bool = True
    supports_join: bool = False


class BaseWarehouseConnector(ABC):
    """Abstract base class for warehouse connectors

    This provides a unified interface for connecting to and querying
    different data warehouses (BigQuery, Snowflake, Redshift, etc.)
    """

    def __init__(self, credentials: dict[str, Any], config: dict[str, Any]):
        """Initialize connector with credentials and configuration

        Args:
            credentials: Decrypted credentials dictionary
            config: Configuration options (timeout, cache settings, etc.)
        """
        self.credentials = credentials
        self.config = config

    @abstractmethod
    def execute_query(self, sql: str, params: Optional[dict[str, Any]] = None) -> QueryResult:
        """Execute SQL query on warehouse

        Args:
            sql: SQL query string to execute
            params: Optional query parameters for parameterized queries

        Returns:
            QueryResult with rows, columns, and execution metadata

        Raises:
            Exception: If query execution fails
        """
        pass

    @abstractmethod
    def get_schema(self, schema_name: Optional[str] = None) -> list[TableSchema]:
        """Retrieve available tables and columns

        Args:
            schema_name: Optional schema/dataset name to filter by

        Returns:
            List of TableSchema objects describing available tables

        Raises:
            Exception: If schema retrieval fails
        """
        pass

    @abstractmethod
    def estimate_cost(self, sql: str) -> QueryCost:
        """Estimate query cost before execution

        Args:
            sql: SQL query string to estimate

        Returns:
            QueryCost with estimated bytes and cost in USD

        Note:
            Some warehouses may not support cost estimation.
            In that case, return QueryCost with zeros and a message.
        """
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """Test if connection credentials are valid

        Returns:
            True if connection succeeds, False otherwise
        """
        pass

    def supports_push_down(self) -> PushDownCapabilities:
        """Declare which optimizations are supported

        Returns:
            PushDownCapabilities indicating which optimizations this connector supports

        Note:
            Override this method if your connector supports additional optimizations
            like aggregation push-down or joins.
        """
        return PushDownCapabilities(
            supports_predicate=True,
            supports_projection=True,
            supports_aggregation=False,
            supports_limit=True,
            supports_join=False,
        )

    def get_timeout(self) -> int:
        """Get query timeout in seconds

        Returns:
            Timeout value from config, or 300 seconds (5 minutes) as default
        """
        return self.config.get("timeout_seconds", 300)

    def close(self) -> None:
        """Close connection and clean up resources

        Override this method if your connector needs cleanup.
        Called when the connector is no longer needed.
        """
        pass
