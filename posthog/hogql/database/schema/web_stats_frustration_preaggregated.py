from pydantic import Field

from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    UnknownDatabaseField,
)

from posthog.clickhouse.preaggregation.web_stats_frustration_preaggregated_sql import (
    DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE,
)


class WebStatsFrustrationPreaggregatedTable(Table):
    description: str = (
        "Pre-aggregated per-path web analytics frustration signals (rage clicks, dead clicks, errors), computed per "
        "precompute job and used internally by the web analytics product. Metric columns are AggregateFunction states "
        "that must be merged."
    )
    # Mirrors `WebStatsPathsPreaggregatedTable`: deterministic replica selection
    # via `load_balancing="in_order"` (read-your-writes) and shard pruning via
    # `optimize_skip_unused_shards=1` (sharded by `sipHash64(job_id)`, and the
    # read filters `job_id IN (...)`).
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order", optimize_skip_unused_shards=True)
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(
            name="job_id", description="Identifier of the precompute job that produced this row; reads filter by it."
        ),
        "time_window_start": DateTimeDatabaseField(
            name="time_window_start", description="Start of the time window this aggregated row covers."
        ),
        "breakdown_value": StringDatabaseField(name="breakdown_value", description="Page path this row aggregates."),
        "sum_rage_clicks_state": UnknownDatabaseField(
            name="sum_rage_clicks_state",
            description="AggregateFunction(sum) state for rage-click count; merge to read.",
        ),
        "sum_dead_clicks_state": UnknownDatabaseField(
            name="sum_dead_clicks_state",
            description="AggregateFunction(sum) state for dead-click count; merge to read.",
        ),
        "sum_errors_state": UnknownDatabaseField(
            name="sum_errors_state", description="AggregateFunction(sum) state for error count; merge to read."
        ),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE()

    def to_printed_hogql(self):
        return "web_stats_frustration_preaggregated"
