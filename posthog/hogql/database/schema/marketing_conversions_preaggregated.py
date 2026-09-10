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

from posthog.clickhouse.preaggregation.marketing_conversions_sql import (
    DISTRIBUTED_MARKETING_CONVERSIONS_TABLE,
    MARKETING_CONVERSIONS_TRACKED_FIELD_NAMES,
)


def _build_fields() -> dict[str, FieldOrTable]:
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(
            name="job_id", description="Identifier of the preaggregation job that produced this row."
        ),
        "person_id": StringDatabaseField(name="person_id", description="Person who converted; join to `persons`."),
        "conversion_timestamp": DateTimeDatabaseField(
            name="conversion_timestamp", description="When the conversion event occurred (UTC)."
        ),
        "conversion_math_value": FloatDatabaseField(
            name="conversion_math_value",
            description="Numeric value of the conversion under the goal's math aggregation (e.g. summed property or count).",
        ),
        "session_id": StringDatabaseField(
            name="session_id", description="Session in which the conversion occurred; join to `sessions`."
        ),
    }
    for tracked_name in MARKETING_CONVERSIONS_TRACKED_FIELD_NAMES:
        col = f"{tracked_name}_name"
        fields[col] = StringDatabaseField(
            name=col, description=f"Value of the '{tracked_name}' marketing attribute for the converting session."
        )
    fields["computed_at"] = DateTimeDatabaseField(
        name="computed_at", description="When this preaggregated row was computed; also the ReplacingMergeTree version."
    )
    fields["expires_at"] = DateDatabaseField(
        name="expires_at", description="Date when this row expires and is dropped via TTL."
    )
    return fields


class MarketingConversionsPreaggregatedTable(Table):
    description: str = (
        "Internal preaggregated table of marketing conversion events, one row per conversion with the "
        "tracked marketing attributes of the converting session. Powers marketing analytics conversion reporting."
    )
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )

    fields: dict[str, FieldOrTable] = _build_fields()

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_MARKETING_CONVERSIONS_TABLE()

    def to_printed_hogql(self):
        return "marketing_conversions_preaggregated"
