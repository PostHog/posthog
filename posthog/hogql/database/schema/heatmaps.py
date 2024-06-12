from posthog.hogql.database.models import (
    StringDatabaseField,
    DateTimeDatabaseField,
    IntegerDatabaseField,
    Table,
    FieldOrTable,
    BooleanDatabaseField,
)


class HeatmapsTable(Table):
    fields: dict[str, FieldOrTable] = {
        "session_id": StringDatabaseField(name="session_id"),
        "team_id": IntegerDatabaseField(name="team_id"),
        "distinct_id": StringDatabaseField(name="distinct_id"),
        "x": IntegerDatabaseField(name="x"),
        "y": IntegerDatabaseField(name="y"),
        "scale_factor": IntegerDatabaseField(name="scale_factor"),
        "viewport_width": IntegerDatabaseField(name="viewport_width"),
        "viewport_height": IntegerDatabaseField(name="viewport_height"),
        "pointer_target_fixed": BooleanDatabaseField(name="pointer_target_fixed"),
        "current_url": StringDatabaseField(name="current_url"),
        "timestamp": DateTimeDatabaseField(name="timestamp"),
        "type": StringDatabaseField(name="type"),
    }

    def to_printed_clickhouse(self, context):
        return "heatmaps"

    def to_printed_hogql(self):
        return "heatmaps"
