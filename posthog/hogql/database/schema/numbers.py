from typing import Dict

from posthog.hogql.database.models import (
    IntegerDatabaseField,
    FieldOrTable,
    FunctionCallTable,
)

NUMBERS_TABLE_FIELDS = {
    "number": IntegerDatabaseField(name="number"),
}


class NumbersTable(FunctionCallTable):
    fields: Dict[str, FieldOrTable] = NUMBERS_TABLE_FIELDS

    name = "numbers"
    min_args = 1
    max_args = 2

    def to_printed_clickhouse(self, context):
        return "numbers"

    def to_printed_hogql(self):
        return "numbers"
