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

from posthog.clickhouse.preaggregation.web_stats_preaggregated_sql import DISTRIBUTED_WEB_STATS_PREAGGREGATED_TABLE


class WebStatsPreaggregatedTable(Table):
    description: str = (
        "Pre-aggregated web analytics stats broken down by a single dimension (breakdown_by/breakdown_value), computed "
        "per precompute job and used internally by the web analytics product. Metric columns are AggregateFunction "
        "states that must be merged."
    )
    # Mirrors `WebOverviewPreaggregatedTable`: deterministic replica selection
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
        "breakdown_by": StringDatabaseField(
            name="breakdown_by",
            description="Name of the dimension this row is broken down by (e.g. 'Browser', 'Country').",
        ),
        "breakdown_value": StringDatabaseField(
            name="breakdown_value", description="Value of the breakdown_by dimension for this row."
        ),
        "uniq_users_state": UnknownDatabaseField(
            name="uniq_users_state", description="AggregateFunction(uniq) state for unique users; merge to read."
        ),
        "sum_pageviews_state": UnknownDatabaseField(
            name="sum_pageviews_state", description="AggregateFunction(sum) state for pageview count; merge to read."
        ),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_WEB_STATS_PREAGGREGATED_TABLE()

    def to_printed_hogql(self):
        return "web_stats_preaggregated"
