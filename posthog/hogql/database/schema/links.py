from posthog.hogql.database.models import (
    StringDatabaseField,
    DateTimeDatabaseField,
    Table,
    FieldOrTable,
)


class LinksTable(Table):
    fields: dict[str, FieldOrTable] = {
        "id": StringDatabaseField(name="id", nullable=False),
        "destination": StringDatabaseField(name="destination", nullable=False),
        "short_link_domain": StringDatabaseField(name="short_link_domain", nullable=False),
        "short_code": StringDatabaseField(name="short_code", nullable=True),
        "created_at": DateTimeDatabaseField(name="created_at", nullable=False),
        "updated_at": DateTimeDatabaseField(name="updated_at", nullable=False),
        "description": StringDatabaseField(name="description", nullable=True),
    }

    def to_printed_clickhouse(self, context):
        return "links"

    def to_printed_hogql(self):
        return "links"
