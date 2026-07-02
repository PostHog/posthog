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
    description: str = "General-purpose vector embeddings keyed by domain and id, used for semantic search."
    fields: dict[str, FieldOrTable] = {
        "domain": StringDatabaseField(
            name="domain", nullable=False, description="Namespace grouping embeddings of the same kind."
        ),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "id": StringDatabaseField(
            name="id", nullable=False, description="Identifier of the embedded item within its domain."
        ),
        "vector": FloatArrayDatabaseField(
            name="vector",
            nullable=False,
            description="The embedding vector; compare with `cosineDistance`/`L2Distance` for semantic search.",
        ),
        "text": StringDatabaseField(name="text", nullable=False, description="The text content that was embedded."),
        "properties": StringJSONDatabaseField(
            name="properties", nullable=False, description="JSON metadata associated with the embedded item."
        ),
        "timestamp": DateTimeDatabaseField(
            name="timestamp",
            nullable=False,
            description="When the embedding was written; also the ReplacingMergeTree version.",
        ),
        "is_deleted": IntegerDatabaseField(
            name="is_deleted",
            nullable=False,
            description="Soft-delete marker (1 if deleted); used for ReplacingMergeTree dedup.",
        ),
    }

    def to_printed_clickhouse(self, context):
        return "pg_embeddings"

    def to_printed_hogql(self):
        return "pg_embeddings"
