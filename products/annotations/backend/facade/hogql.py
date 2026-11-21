"""HogQL surface for annotations.

Exposed as `system.annotations`, so the SQL editor, insights and MCP can read annotations, while every
write still goes through the annotations API.
"""

from posthog.hogql.database.postgres_table import PostgresTable

from products.annotations.backend.logic import hogql

__all__ = ["annotations"]

annotations: PostgresTable = hogql.annotations
