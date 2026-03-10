import pyarrow as pa
import deltalake as deltalake

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
)


def postgres_type_to_hogql_field(postgres_type: str) -> str:
    """Map Postgres data types to HogQL field type names.

    This uses the authoritative Postgres schema metadata instead of guessing from data.
    """
    postgres_type_lower = postgres_type.lower()

    if postgres_type_lower in ("json", "jsonb"):
        return StringJSONDatabaseField.__name__
    elif postgres_type_lower in ("bigint",):
        return IntegerDatabaseField.__name__
    elif postgres_type_lower in ("integer", "smallint", "int", "int2", "int4", "int8"):
        return IntegerDatabaseField.__name__
    elif postgres_type_lower in ("numeric", "decimal", "real", "double precision", "float", "float4", "float8"):
        return FloatDatabaseField.__name__
    elif postgres_type_lower == "boolean" or postgres_type_lower == "bool":
        return BooleanDatabaseField.__name__
    elif postgres_type_lower == "date":
        return DateDatabaseField.__name__
    elif postgres_type_lower.startswith("timestamp") or postgres_type_lower.startswith("time"):
        return DateTimeDatabaseField.__name__
    else:
        # Default to string for text, varchar, uuid, arrays, etc.
        return StringDatabaseField.__name__


class HogQLSchema:
    schema: dict[str, str]
    postgres_type_map: dict[str, str] | None

    def __init__(self, existing_schema: dict[str, str] | None = None, postgres_type_map: dict[str, str] | None = None):
        """Initialize HogQL schema with optional existing types and Postgres type metadata.

        Args:
            existing_schema: Previously detected HogQL types (for backwards compatibility)
            postgres_type_map: Map of column_name -> postgres_type from schema metadata
        """
        self.schema = existing_schema.copy() if existing_schema else {}
        self.postgres_type_map = postgres_type_map

    def add_pyarrow_table(self, table: pa.Table) -> None:
        for field in table.schema:
            self.add_field(field, table.column(field.name))

    def add_field(self, field: pa.Field, column: pa.ChunkedArray) -> None:
        existing_type = self.schema.get(field.name)
        if existing_type is not None:
            return

        # First, try using Postgres schema metadata if available
        if self.postgres_type_map and field.name in self.postgres_type_map:
            postgres_type = self.postgres_type_map[field.name]
            self.schema[field.name] = postgres_type_to_hogql_field(postgres_type)
            return

        if pa.types.is_binary(field.type):
            return

        hogql_type: type[DatabaseField] = DatabaseField

        if pa.types.is_time(field.type):
            hogql_type = DateTimeDatabaseField
        elif pa.types.is_timestamp(field.type):
            hogql_type = DateTimeDatabaseField
        elif pa.types.is_date(field.type):
            hogql_type = DateDatabaseField
        elif pa.types.is_decimal(field.type):
            hogql_type = FloatDatabaseField
        elif pa.types.is_floating(field.type):
            hogql_type = FloatDatabaseField
        elif pa.types.is_boolean(field.type):
            hogql_type = BooleanDatabaseField
        elif pa.types.is_integer(field.type):
            hogql_type = IntegerDatabaseField
        elif pa.types.is_string(field.type):
            hogql_type = StringDatabaseField

            # Checking for JSON string columns with the first non-null value in the column
            for value in column:
                value_str = value.as_py()
                if value_str is not None:
                    assert isinstance(value_str, str)
                    if value_str.startswith("{") or value_str.startswith("["):
                        hogql_type = StringJSONDatabaseField
                    break

        self.schema[field.name] = hogql_type.__name__

    def to_hogql_types(self) -> dict[str, str]:
        return self.schema
