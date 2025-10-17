from posthog.hogql.ast import SelectQuery
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.argmax import argmax_select
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    FloatArrayDatabaseField,
    IntegerDatabaseField,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    Table,
)

from products.error_tracking.backend.embedding import DOCUMENT_EMBEDDINGS

DOCUMENT_EMBEDDINGS_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "product": StringDatabaseField(name="product", nullable=False),
    "document_type": StringDatabaseField(name="document_type", nullable=False),
    "model_name": StringDatabaseField(name="model_name", nullable=False),
    "rendering": StringDatabaseField(name="rendering", nullable=False),
    "document_id": StringDatabaseField(name="document_id", nullable=False),
    "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
    "inserted_at": DateTimeDatabaseField(name="inserted_at", nullable=False),
    "embedding": FloatArrayDatabaseField(name="embedding", nullable=False),
}


def select_from_embeddings_table(requested_fields: dict[str, list[str | int]]):
    # Always include "document_id", as it's key to any further joins
    if "document_id" not in requested_fields:
        requested_fields = {**requested_fields, "document_id": ["document_id"]}
    select = argmax_select(
        table_name=f"raw_document_embeddings",
        select_fields=requested_fields,
        # I /think/ this is the right set of fields to group by, but I'm not actually certain.
        # In theory this (plus team_id) is the set of columns that uniquely identify a document embedding.
        group_fields=["product", "document_type", "model_name", "rendering", "document_id", "timestamp"],
        argmax_field="inserted_at",
    )
    select.settings = HogQLQuerySettings(optimize_aggregation_in_order=True)
    return select


class RawDocumentEmbeddingsTable(Table):
    fields: dict[str, FieldOrTable] = DOCUMENT_EMBEDDINGS_FIELDS

    def to_printed_clickhouse(self, context):
        return DOCUMENT_EMBEDDINGS

    def to_printed_hogql(self):
        return f"raw_document_embeddings"


class DocumentEmbeddingsTable(LazyTable):
    fields: dict[str, FieldOrTable] = DOCUMENT_EMBEDDINGS_FIELDS

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: SelectQuery,
    ):
        return select_from_embeddings_table(table_to_add.fields_accessed)

    def to_printed_clickhouse(self, context):
        return DOCUMENT_EMBEDDINGS

    def to_printed_hogql(self):
        return "document_embeddings"
