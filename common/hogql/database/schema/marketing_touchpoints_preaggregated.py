from pydantic import Field

from common.hogql.backend import resolve_backend_symbol as _resolve_backend_symbol
from common.hogql.constants import HogQLQuerySettings
from common.hogql.database.models import (
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

DISTRIBUTED_MARKETING_TOUCHPOINTS_TABLE = _resolve_backend_symbol(
    "posthog.clickhouse.preaggregation.marketing_touchpoints_sql", "DISTRIBUTED_MARKETING_TOUCHPOINTS_TABLE"
)
MARKETING_TOUCHPOINTS_TRACKED_FIELD_NAMES = _resolve_backend_symbol(
    "posthog.clickhouse.preaggregation.marketing_touchpoints_sql", "MARKETING_TOUCHPOINTS_TRACKED_FIELD_NAMES"
)


def _build_fields() -> dict[str, FieldOrTable]:
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(name="job_id"),
        "person_id": StringDatabaseField(name="person_id"),
        "touchpoint_timestamp": DateTimeDatabaseField(name="touchpoint_timestamp"),
    }
    for tracked_name in MARKETING_TOUCHPOINTS_TRACKED_FIELD_NAMES:
        col = f"{tracked_name}_name"
        fields[col] = StringDatabaseField(name=col)
    fields["computed_at"] = DateTimeDatabaseField(name="computed_at")
    fields["expires_at"] = DateDatabaseField(name="expires_at")
    return fields


class MarketingTouchpointsPreaggregatedTable(Table):
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order")
    )

    fields: dict[str, FieldOrTable] = _build_fields()

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_MARKETING_TOUCHPOINTS_TABLE()

    def to_printed_hogql(self):
        return "marketing_touchpoints_preaggregated"
