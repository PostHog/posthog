from posthog.hogql.database.models import (
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    Table,
    FieldOrTable,
)


class ShortLinksTable(Table):
    fields: dict[str, FieldOrTable] = {
        "id": StringDatabaseField(name="id", nullable=False),
        "destination": StringDatabaseField(name="destination", nullable=False),
        "origin_domain": StringDatabaseField(name="origin_domain", nullable=False),
        "origin_key": StringDatabaseField(name="origin_key", nullable=True),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "created_at": DateTimeDatabaseField(name="created_at", nullable=False),
        "updated_at": DateTimeDatabaseField(name="updated_at", nullable=False),
        "description": StringDatabaseField(name="description", nullable=True),
        "tags": StringDatabaseField(name="tags", nullable=True),
        "comments": StringDatabaseField(name="comments", nullable=True),
    }

    def to_printed_clickhouse(self, context):
        return "short_links"

    def to_printed_hogql(self):
        return "short_links"
