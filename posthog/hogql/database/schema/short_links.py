from posthog.hogql.database.models import (
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    Table,
    FieldOrTable,
)


class ShortLinksTable(Table):
    fields: dict[str, FieldOrTable] = {
        "key": StringDatabaseField(name="key", nullable=False),
        "hashed_key": StringDatabaseField(name="hashed_key", nullable=False),
        "destination_url": StringDatabaseField(name="destination_url", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "created_at": DateTimeDatabaseField(name="created_at", nullable=False),
        "updated_at": DateTimeDatabaseField(name="updated_at", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "short_links"

    def to_printed_hogql(self):
        return "short_links"
