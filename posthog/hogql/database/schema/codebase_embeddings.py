from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    FloatArrayDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)


class CodebaseEmbeddingsTable(Table):
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "user_id": IntegerDatabaseField(name="user_id", nullable=False),
        "codebase_id": StringDatabaseField(name="codebase_id", nullable=False),
        "artifact_id": StringDatabaseField(name="artifact_id", nullable=False),
        "vector": FloatArrayDatabaseField(name="vector", nullable=False),
        "properties": StringJSONDatabaseField(name="properties", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "codebase_embeddings"

    def to_printed_hogql(self):
        return "codebase_embeddings"
