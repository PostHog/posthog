from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.marketing_touchpoints_sql import (
    DISTRIBUTED_MARKETING_TOUCHPOINTS_TABLE,
    MARKETING_TOUCHPOINTS_TRACKED_FIELD_NAMES,
)


def _build_fields() -> dict[str, FieldOrTable]:
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(
            name="job_id", description="Identifier of the preaggregation job that produced this row."
        ),
        "person_id": StringDatabaseField(
            name="person_id", description="Person who experienced the touchpoint; join to `persons`."
        ),
        "touchpoint_timestamp": DateTimeDatabaseField(
            name="touchpoint_timestamp", description="When the marketing touchpoint occurred (UTC)."
        ),
    }
    for tracked_name in MARKETING_TOUCHPOINTS_TRACKED_FIELD_NAMES:
        col = f"{tracked_name}_name"
        fields[col] = StringDatabaseField(
            name=col, description=f"Value of the '{tracked_name}' marketing attribute for this touchpoint."
        )
    fields["computed_at"] = DateTimeDatabaseField(
        name="computed_at", description="When this preaggregated row was computed; also the ReplacingMergeTree version."
    )
    fields["expires_at"] = DateDatabaseField(
        name="expires_at", description="Date when this row expires and is dropped via TTL."
    )
    return fields


class MarketingTouchpointsPreaggregatedTable(Table):
    description: str = (
        "Internal preaggregated table of marketing touchpoints (one row per person interaction with a marketing "
        "channel), carrying the tracked marketing attributes. Feeds conversion attribution in marketing analytics."
    )
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )

    fields: dict[str, FieldOrTable] = _build_fields()

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_MARKETING_TOUCHPOINTS_TABLE()

    def to_printed_hogql(self):
        return "marketing_touchpoints_preaggregated"
