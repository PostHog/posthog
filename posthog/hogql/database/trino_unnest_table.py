from typing import TYPE_CHECKING

from posthog.hogql.database.models import (
    DANGEROUS_NoTeamIdCheckTable,
    FieldOrTable,
    FunctionCallTable,
    UnknownDatabaseField,
)

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext


TRINO_UNNEST_TABLE_NAME = "__trino_unnest"


class TrinoUnnestTable(FunctionCallTable, DANGEROUS_NoTeamIdCheckTable):
    name: str
    fields: dict[str, FieldOrTable] = {
        "value": UnknownDatabaseField(name="value"),
        "value_2": UnknownDatabaseField(name="value_2"),
        "value_3": UnknownDatabaseField(name="value_3"),
        "value_4": UnknownDatabaseField(name="value_4"),
        "value_5": UnknownDatabaseField(name="value_5"),
    }
    min_args: int = 1
    max_args: int = 1

    def to_printed_hogql(self) -> str:
        return self.name

    def to_printed_trino(self, context: "HogQLContext") -> str:
        return "UNNEST"


TRINO_UNNEST_TABLE = TrinoUnnestTable(name=TRINO_UNNEST_TABLE_NAME)


def resolve_internal_trino_table_function(table_name_chain: list[str]) -> TrinoUnnestTable | None:
    return TRINO_UNNEST_TABLE if table_name_chain == [TRINO_UNNEST_TABLE_NAME] else None
