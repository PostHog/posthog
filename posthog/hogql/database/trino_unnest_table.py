from typing import TYPE_CHECKING

from posthog.hogql.database.models import (
    DANGEROUS_NoTeamIdCheckTable,
    FieldOrTable,
    FunctionCallTable,
    TableNode,
    UnknownDatabaseField,
)

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.database.database import Database


TRINO_UNNEST_TABLE_NAME = "__trino_unnest"


class TrinoUnnestTable(FunctionCallTable, DANGEROUS_NoTeamIdCheckTable):
    name: str
    fields: dict[str, FieldOrTable] = {"value": UnknownDatabaseField(name="value")}
    min_args: int = 1
    max_args: int = 1

    def to_printed_hogql(self) -> str:
        return self.name

    def to_printed_trino(self, context: "HogQLContext") -> str:
        return "UNNEST"


def ensure_trino_unnest_table(database: "Database") -> None:
    if not database.has_table(TRINO_UNNEST_TABLE_NAME):
        database.tables.add_child(
            TableNode(name=TRINO_UNNEST_TABLE_NAME, table=TrinoUnnestTable(name=TRINO_UNNEST_TABLE_NAME)),
            table_conflict_mode="override",
        )
