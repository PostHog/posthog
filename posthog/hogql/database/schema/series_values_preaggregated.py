from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringDatabaseField,
    Table,
)

from posthog.clickhouse.preaggregation.series_values_preaggregated_sql import (
    DISTRIBUTED_SERIES_VALUES_PREAGGREGATED_TABLE,
)


class SeriesValuesPreaggregatedTable(Table):
    description: str = (
        "Pre-aggregated insight series values, one finished value per series, breakdown value and time window, "
        "computed per precompute job and used internally by insight queries."
    )
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order", optimize_skip_unused_shards=True)
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(
            name="job_id", description="Identifier of the precompute job that produced this row; reads filter by it."
        ),
        "time_window_start": DateTimeDatabaseField(
            name="time_window_start", description="Start of the time window this row covers."
        ),
        "series_key": StringDatabaseField(
            name="series_key", description="Identifies the series within the job; empty for single-series jobs."
        ),
        "breakdown_value": StringArrayDatabaseField(
            name="breakdown_value", description="Breakdown values for this row; empty when there is no breakdown."
        ),
        "value": FloatDatabaseField(name="value", description="Finished value for the series in this time window."),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_SERIES_VALUES_PREAGGREGATED_TABLE()

    def to_printed_hogql(self):
        return "series_values_preaggregated"
