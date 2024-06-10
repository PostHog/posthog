from posthog.hogql.database.models import (
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    FieldOrTable,
    Table,
    FloatDatabaseField,
    StringJSONDatabaseField,
)


class WebVitalsTable(Table):
    fields: dict[str, FieldOrTable] = {
        "session_id": StringDatabaseField(name="session_id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "timestamp": DateTimeDatabaseField(name="timestamp"),
        "distinct_id": StringDatabaseField(name="distinct_id"),
        "current_url": StringDatabaseField(name="current_url"),
        "fcp": FloatDatabaseField(name="fcp"),
        "lcp": FloatDatabaseField(name="lcp"),
        "cls": FloatDatabaseField(name="cls"),
        "inp": FloatDatabaseField(name="inp"),
        "properties": StringJSONDatabaseField(name="properties"),
    }

    def to_printed_clickhouse(self, context):
        return "web_vitals"

    def to_printed_hogql(self):
        return "web_vitals"
