from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateDatabaseField,
    FieldOrTable,
    IntegerArrayDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.retention_curve_sql import DISTRIBUTED_RETENTION_CURVE_TABLE


class RetentionCurveTable(Table):
    # `load_balancing="in_order"` so reads land on the replica that wrote the curve
    # (read-your-writes after a materialisation), and `optimize_skip_unused_shards=1` to prune
    # shards using the team_id filter.
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order", optimize_skip_unused_shards=True)
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "kind": StringDatabaseField(name="kind"),
        "person_id": StringDatabaseField(name="person_id"),
        "first_seen_day": DateDatabaseField(name="first_seen_day"),
        "active_offsets": IntegerArrayDatabaseField(name="active_offsets"),
        "computed_at": StringDatabaseField(name="computed_at"),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_RETENTION_CURVE_TABLE()

    def to_printed_hogql(self):
        return "retention_curve"
