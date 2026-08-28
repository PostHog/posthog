from posthog.hogql.database.models import (
    DANGEROUS_NoTeamIdCheckTable,
    FieldOrTable,
    FunctionCallTable,
    UnknownDatabaseField,
)


class TrinoUnnestTable(FunctionCallTable, DANGEROUS_NoTeamIdCheckTable):
    name: str
    fields: dict[str, FieldOrTable] = {"value": UnknownDatabaseField(name="value")}
    min_args: int = 1
    max_args: int = 1

    def to_printed_hogql(self) -> str:
        return self.name

    def to_printed_trino(self, context) -> str:
        return "UNNEST"
