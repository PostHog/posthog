from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    FloatArrayDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
)


class PgEmbeddingsTable(Table):
    fields: dict[str, FieldOrTable] = {
        "domain": StringDatabaseField(name="domain", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "id": StringDatabaseField(name="id", nullable=False),
        "vector": FloatArrayDatabaseField(name="vector", nullable=False),
        "text": StringDatabaseField(name="text", nullable=False),
        "properties": StringJSONDatabaseField(name="properties", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "is_deleted": IntegerDatabaseField(name="is_deleted", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "pg_embeddings"

    def to_printed_hogql(self):
        return "pg_embeddings"
