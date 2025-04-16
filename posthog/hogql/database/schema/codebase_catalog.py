from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)


class CodebaseCatalogTable(Table):
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "user_id": IntegerDatabaseField(name="user_id", nullable=False),
        "codebase_id": StringDatabaseField(name="codebase_id", nullable=False),
        "artifact_id": StringDatabaseField(name="artifact_id", nullable=False),
        "branch": StringDatabaseField(name="branch", nullable=False),
        "parent_artifact_id": StringDatabaseField(name="parent_artifact_id", nullable=False),
        "type": StringDatabaseField(name="type", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "sign": IntegerDatabaseField(name="sign", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "codebase_catalog"

    def to_printed_hogql(self):
        return "codebase_catalog"
