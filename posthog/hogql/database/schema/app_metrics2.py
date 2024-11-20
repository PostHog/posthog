from posthog.hogql.database.models import (
    Table,
    IntegerDatabaseField,
    StringDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
)

APP_METRICS2_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id"),
    "app_source": StringDatabaseField(name="app_source"),
    "app_source_id": StringDatabaseField(name="app_source_id"),
    "instance_id": StringDatabaseField(name="instance_id"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "metric_name": StringDatabaseField(name="metric_name"),
    "metric_kind": StringDatabaseField(name="metric_kind"),
    "count": IntegerDatabaseField(name="count"),
}


class AppMetrics2Table(Table):
    fields: dict[str, FieldOrTable] = APP_METRICS2_FIELDS

    def to_printed_clickhouse(self, context):
        return "app_metrics2"

    def to_printed_hogql(self):
        return "app_metrics2"
