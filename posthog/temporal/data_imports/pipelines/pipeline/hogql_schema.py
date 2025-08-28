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


class HogQLSchema:
    schema: dict[str, str]

    def __init__(self):
        self.schema = {}

    def add_pyarrow_table(self, table: pa.Table) -> None:
        for field in table.schema:
            self.add_field(field, table.column(field.name))

    def add_field(self, field: pa.Field, column: pa.ChunkedArray) -> None:
        existing_type = self.schema.get(field.name)
        if existing_type is not None and existing_type != StringDatabaseField.__name__:
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
