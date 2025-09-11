from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)


class HeatmapsTable(Table):
    fields: dict[str, FieldOrTable] = {
        "session_id": StringDatabaseField(name="session_id", nullable=False),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
        "x": IntegerDatabaseField(name="x", nullable=False),
        "y": IntegerDatabaseField(name="y", nullable=False),
        "scale_factor": IntegerDatabaseField(name="scale_factor", nullable=False),
        "viewport_width": IntegerDatabaseField(name="viewport_width", nullable=False),
        "viewport_height": IntegerDatabaseField(name="viewport_height", nullable=False),
        "pointer_target_fixed": BooleanDatabaseField(name="pointer_target_fixed", nullable=False),
        "current_url": StringDatabaseField(name="current_url", nullable=False),
        "timestamp": DateTimeDatabaseField(name="timestamp", nullable=False),
        "type": StringDatabaseField(name="type", nullable=False),
    }

    def to_printed_clickhouse(self, context):
        return "heatmaps"

    def to_printed_hogql(self):
        return "heatmaps"
