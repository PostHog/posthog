from posthog.hogql.database.direct_sql_table import DirectSQLTable
from posthog.hogql.database.models import FieldOrTable
from posthog.hogql.errors import QueryError
from posthog.hogql.escape_sql import escape_snowflake_identifier


class DirectSnowflakeTable(DirectSQLTable):
    snowflake_catalog: str | None = None
    snowflake_schema: str
    snowflake_table_name: str

    # Snowflake stores object names uppercase but resolves unquoted identifiers case-insensitively.
    # We quote every identifier (quoted names are case-sensitive in Snowflake), so resolve a HogQL
    # field to its canonically-cased column regardless of how the user typed it, then print that.
    def _canonical_field_key(self, name: str | int) -> str | None:
        target = str(name).lower()
        for key in self.fields:
            if key.lower() == target:
                return key
        return None

    def has_field(self, name: str | int) -> bool:
        return super().has_field(name) or self._canonical_field_key(name) is not None

    def get_field(self, name: str | int) -> FieldOrTable:
        if super().has_field(name):
            return super().get_field(name)
        key = self._canonical_field_key(name)
        if key is not None:
            return self.fields[key]
        return super().get_field(name)

    def to_printed_snowflake(self, context) -> str:
        if not self.snowflake_schema.strip():
            raise QueryError("Direct Snowflake tables require a schema name.")
        parts = []
        if self.snowflake_catalog:
            parts.append(escape_snowflake_identifier(self.snowflake_catalog))
        parts.extend(
            [
                escape_snowflake_identifier(self.snowflake_schema),
                escape_snowflake_identifier(self.snowflake_table_name),
            ]
        )
        return ".".join(parts)

    def to_printed_postgres(self, context) -> str:
        raise QueryError("Direct Snowflake tables cannot be printed into Postgres SQL")

    def to_printed_clickhouse(self, context) -> str:
        raise QueryError("Direct Snowflake tables cannot be printed into ClickHouse SQL")
