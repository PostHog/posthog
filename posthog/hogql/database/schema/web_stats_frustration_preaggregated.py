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
    # Mirrors `WebStatsPathsPreaggregatedTable`: deterministic replica selection
    # via `load_balancing="in_order"` (read-your-writes) and shard pruning via
    # `optimize_skip_unused_shards=1` (sharded by `sipHash64(job_id)`, and the
    # read filters `job_id IN (...)`).
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order", optimize_skip_unused_shards=True)
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(name="job_id"),
        "time_window_start": DateTimeDatabaseField(name="time_window_start"),
        "breakdown_value": StringDatabaseField(name="breakdown_value"),
        "sum_rage_clicks_state": UnknownDatabaseField(name="sum_rage_clicks_state"),
        "sum_dead_clicks_state": UnknownDatabaseField(name="sum_dead_clicks_state"),
        "sum_errors_state": UnknownDatabaseField(name="sum_errors_state"),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE()

    def to_printed_hogql(self):
        return "web_stats_frustration_preaggregated"
