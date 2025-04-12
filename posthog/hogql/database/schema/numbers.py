from typing import Optional

from posthog.hogql.database.models import (
    IntegerDatabaseField,
    FieldOrTable,
    FunctionCallTable,
)

NUMBERS_TABLE_FIELDS: dict[str, FieldOrTable] = {
    "number": IntegerDatabaseField(name="number", nullable=False),
}


class NumbersTable(FunctionCallTable):
    fields: dict[str, FieldOrTable] = NUMBERS_TABLE_FIELDS

    name: str = "numbers"
    min_args: Optional[int] = 1
    max_args: Optional[int] = 2

    def to_printed_clickhouse(self, context):
        return "numbers"

    def to_printed_hogql(self):
        return "numbers"
