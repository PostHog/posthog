from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    UUIDDatabaseField,
)


class UptimePingsTable(Table):
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "monitor_id": UUIDDatabaseField(name="monitor_id", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "latency_ms": IntegerDatabaseField(name="latency_ms", nullable=False),
        "status_code": IntegerDatabaseField(name="status_code", nullable=False),
        "outcome": StringDatabaseField(name="outcome", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "uptime_pings"

    def to_printed_hogql(self):
        return "uptime_pings"
