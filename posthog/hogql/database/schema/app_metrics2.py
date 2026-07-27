from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

APP_METRICS2_FIELDS: dict[str, FieldOrTable] = {
    "team_id": IntegerDatabaseField(name="team_id", nullable=False),
    "app_source": StringDatabaseField(
        name="app_source",
        nullable=False,
        description="Kind of app that produced the metric, e.g. 'hog_function' or 'plugin'.",
    ),
    "app_source_id": StringDatabaseField(
        name="app_source_id",
        nullable=False,
        description="Identifier of the specific app/function the metric belongs to.",
    ),
    "instance_id": StringDatabaseField(
        name="instance_id",
        nullable=False,
        description="Identifier of the specific run/instance that emitted the metric.",
    ),
    "timestamp": DateTimeDatabaseField(
        name="timestamp", nullable=False, description="Bucketed time the metric count applies to."
    ),
    "metric_name": StringDatabaseField(
        name="metric_name", nullable=False, description="Name of the metric, e.g. 'succeeded', 'failed', 'filtered'."
    ),
    "metric_kind": StringDatabaseField(
        name="metric_kind", nullable=False, description="Category of the metric, e.g. 'success', 'failure', 'other'."
    ),
    "count": IntegerDatabaseField(
        name="count", nullable=False, description="Number of occurrences for this metric in the time bucket."
    ),
}


class AppMetrics2Table(Table):
    description: str = (
        "Aggregated success/failure counts emitted by apps such as hog functions and plugins, bucketed by time."
    )
    fields: dict[str, FieldOrTable] = APP_METRICS2_FIELDS

    def to_printed_clickhouse(self, context):
        return "app_metrics2"

    def to_printed_hogql(self):
        return "app_metrics2"
