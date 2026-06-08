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
        "job_id": StringDatabaseField(name="job_id"),
        "person_id": StringDatabaseField(name="person_id"),
        "conversion_timestamp": DateTimeDatabaseField(name="conversion_timestamp"),
        "conversion_math_value": FloatDatabaseField(name="conversion_math_value"),
        "session_id": StringDatabaseField(name="session_id"),
    }
    for tracked_name in MARKETING_CONVERSIONS_TRACKED_FIELD_NAMES:
        col = f"{tracked_name}_name"
        fields[col] = StringDatabaseField(name=col)
    fields["computed_at"] = DateTimeDatabaseField(name="computed_at")
    fields["expires_at"] = DateDatabaseField(name="expires_at")
    return fields


class MarketingConversionsPreaggregatedTable(Table):
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )

    fields: dict[str, FieldOrTable] = _build_fields()

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_MARKETING_CONVERSIONS_TABLE()

    def to_printed_hogql(self):
        return "marketing_conversions_preaggregated"
