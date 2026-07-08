from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)


class HeatmapsTable(Table):
    description: str = (
        "Individual heatmap interactions (clicks, rage clicks, mouse moves, scrolls) captured from $heatmap events; "
        "one row per interaction, used to build click/scroll heatmaps per URL."
    )
    fields: dict[str, FieldOrTable] = {
        "session_id": StringDatabaseField(
            name="session_id",
            nullable=False,
            description="Recording session the interaction belongs to; matches `session_replay_events.session_id`.",
        ),
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(
            name="distinct_id", nullable=False, description="Identifier of the user/device that interacted."
        ),
        "x": IntegerDatabaseField(
            name="x",
            nullable=False,
            description="X coordinate snapped to an NxN grid; multiply by `scale_factor` for the original pixel value.",
        ),
        "y": IntegerDatabaseField(
            name="y",
            nullable=False,
            description="Y coordinate snapped to an NxN grid; multiply by `scale_factor` for the original pixel value.",
        ),
        "scale_factor": IntegerDatabaseField(
            name="scale_factor", nullable=False, description="Grid resolution applied to `x`/`y` coordinates."
        ),
        "viewport_width": IntegerDatabaseField(
            name="viewport_width", nullable=False, description="Browser viewport width at capture time, in pixels."
        ),
        "viewport_height": IntegerDatabaseField(
            name="viewport_height", nullable=False, description="Browser viewport height at capture time, in pixels."
        ),
        "pointer_target_fixed": BooleanDatabaseField(
            name="pointer_target_fixed",
            nullable=False,
            description="Whether the clicked element stays fixed when the page scrolls.",
        ),
        "current_url": StringDatabaseField(
            name="current_url", nullable=False, description="URL of the page where the interaction occurred."
        ),
        "timestamp": DateTimeDatabaseField(
            name="timestamp", nullable=False, description="When the interaction occurred (in UTC)."
        ),
        "type": StringDatabaseField(
            name="type",
            nullable=False,
            description="Interaction type, e.g. 'click', 'rageclick', 'mousemove', 'scrolldepth'.",
        ),
    }

    def to_printed_clickhouse(self, context):
        return "heatmaps"

    def to_printed_hogql(self):
        return "heatmaps"
