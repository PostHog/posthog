"""
Source-config wiring for data_warehouse.

Light re-exports of the direct-SQL source option constants. Kept free of heavy
imports (no DB drivers) so the setup-path consumers (the warehouse_sources table
model) add no boot cost.
"""

from products.data_warehouse.backend.direct_mysql import DIRECT_MYSQL_SCHEMA_OPTION, DIRECT_MYSQL_TABLE_OPTION
from products.data_warehouse.backend.direct_postgres import (
    DIRECT_POSTGRES_CATALOG_OPTION,
    DIRECT_POSTGRES_SCHEMA_OPTION,
    DIRECT_POSTGRES_TABLE_OPTION,
)
from products.data_warehouse.backend.direct_snowflake import (
    DIRECT_SNOWFLAKE_CATALOG_OPTION,
    DIRECT_SNOWFLAKE_SCHEMA_OPTION,
    DIRECT_SNOWFLAKE_TABLE_OPTION,
)

__all__ = [
    "DIRECT_MYSQL_SCHEMA_OPTION",
    "DIRECT_MYSQL_TABLE_OPTION",
    "DIRECT_POSTGRES_CATALOG_OPTION",
    "DIRECT_POSTGRES_SCHEMA_OPTION",
    "DIRECT_POSTGRES_TABLE_OPTION",
    "DIRECT_SNOWFLAKE_CATALOG_OPTION",
    "DIRECT_SNOWFLAKE_SCHEMA_OPTION",
    "DIRECT_SNOWFLAKE_TABLE_OPTION",
]
