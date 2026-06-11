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

from posthog.clickhouse.preaggregation.web_stats_paths_preaggregated_sql import (
    DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_TABLE,
)


class WebStatsPathsPreaggregatedTable(Table):
    # Mirrors `WebOverviewPreaggregatedTable`: deterministic replica selection
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
        "uniq_users_state": UnknownDatabaseField(name="uniq_users_state"),
        "sum_pageviews_state": UnknownDatabaseField(name="sum_pageviews_state"),
        "avg_bounce_state": UnknownDatabaseField(name="avg_bounce_state"),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_TABLE()

    def to_printed_hogql(self):
        return "web_stats_paths_preaggregated"
