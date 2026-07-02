from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.conversion_goal_attributed_sql import (
    CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES,
    DISTRIBUTED_CONVERSION_GOAL_ATTRIBUTED_TABLE,
)


def _build_fields() -> dict[str, FieldOrTable]:
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(
            name="job_id", description="Identifier of the preaggregation job that produced this row."
        ),
        "person_id": StringDatabaseField(
            name="person_id", description="Person credited with the conversion; join to `persons`."
        ),
        "conversion_timestamp": DateTimeDatabaseField(
            name="conversion_timestamp", description="When the conversion occurred (UTC)."
        ),
        "conversion_value": FloatDatabaseField(
            name="conversion_value",
            description="Value of the conversion (e.g. revenue or count for the conversion goal).",
        ),
        "touchpoint_timestamp": DateTimeDatabaseField(
            name="touchpoint_timestamp", description="When the attributed marketing touchpoint occurred (UTC)."
        ),
        "touchpoint_weight": FloatDatabaseField(
            name="touchpoint_weight",
            description="Attribution weight of this touchpoint; single-touch is 1.0, multi-touch emits fractional weights summing to 1 across the conversion's rows.",
        ),
    }
    for tracked_name in CONVERSION_GOAL_ATTRIBUTED_TRACKED_FIELD_NAMES:
        col = f"{tracked_name}_name"
        fields[col] = StringDatabaseField(
            name=col, description=f"Value of the '{tracked_name}' marketing attribute for the attributed touchpoint."
        )
    fields["computed_at"] = DateTimeDatabaseField(
        name="computed_at", description="When this preaggregated row was computed; also the ReplacingMergeTree version."
    )
    fields["expires_at"] = DateDatabaseField(
        name="expires_at", description="Date when this row expires and is dropped via TTL."
    )
    return fields


class ConversionGoalAttributedPreaggregatedTable(Table):
    description: str = (
        "Internal preaggregated table holding the attributed output of the conversion-goal pipeline: "
        "one row per (team, job, person, conversion, touchpoint) with the attribution weight for that touchpoint."
    )
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )

    fields: dict[str, FieldOrTable] = _build_fields()

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_CONVERSION_GOAL_ATTRIBUTED_TABLE()

    def to_printed_hogql(self):
        return "conversion_goal_attributed_preaggregated"
