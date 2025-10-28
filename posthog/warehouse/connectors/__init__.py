from typing import TYPE_CHECKING

from posthog.warehouse.connectors.base import (
    BaseWarehouseConnector,
    ColumnSchema,
    PushDownCapabilities,
    QueryCost,
    QueryResult,
    TableSchema,
)

if TYPE_CHECKING:
    pass

__all__ = [
    "BaseWarehouseConnector",
    "ColumnSchema",
    "PushDownCapabilities",
    "QueryCost",
    "QueryResult",
    "TableSchema",
    "get_connector",
]


CONNECTORS = {
    "bigquery": "posthog.warehouse.connectors.bigquery.BigQueryConnector",
    "snowflake": "posthog.warehouse.connectors.snowflake.SnowflakeConnector",
    "redshift": "posthog.warehouse.connectors.redshift.RedshiftConnector",
    "databricks": "posthog.warehouse.connectors.databricks.DatabricksConnector",
}


def get_connector(credentials: dict, config: dict, provider: str) -> BaseWarehouseConnector:
    """Factory function to get appropriate connector

    Args:
        credentials: Decrypted credentials dictionary
        config: Configuration options
        provider: Warehouse provider type ('bigquery', 'snowflake', etc.)

    Returns:
        Instantiated connector for the specified provider

    Raises:
        ValueError: If provider is unknown
        ImportError: If connector implementation is not available
    """
    connector_path = CONNECTORS.get(provider)
    if not connector_path:
        raise ValueError(f"Unknown warehouse provider: {provider}")

    module_path, class_name = connector_path.rsplit(".", 1)

    try:
        module = __import__(module_path, fromlist=[class_name])
        connector_class = getattr(module, class_name)
        return connector_class(credentials, config)
    except ImportError as e:
        raise ImportError(
            f"Connector for {provider} is not available. "
            f"Please ensure required packages are installed. Error: {e}"
        )
