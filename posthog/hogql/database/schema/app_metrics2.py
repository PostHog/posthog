from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

APP_METRICS2_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "app_source": StringDatabaseField(name="app_source", nullable=False),
    "app_source_id": StringDatabaseField(name="app_source_id", nullable=False),
    "instance_id": StringDatabaseField(name="instance_id", nullable=False),
    "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
    "metric_name": StringDatabaseField(name="metric_name", nullable=False),
    "metric_kind": StringDatabaseField(name="metric_kind", nullable=False),
    "count": IntegerDatabaseField(name="count", nullable=False),
}


class AppMetrics2Table(Table):
    fields: dict[str, FieldOrTable] = APP_METRICS2_FIELDS

    def to_printed_clickhouse(self, context):
        return "app_metrics2"

    def to_printed_hogql(self):
        return "app_metrics2"
