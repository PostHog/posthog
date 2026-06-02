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

from posthog.clickhouse.preaggregation.web_goals_preaggregated_sql import DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE


class WebGoalsPreaggregatedTable(Table):
    # Mirrors `WebStatsPathsPreaggregatedTable`: deterministic replica
    # selection via `load_balancing="in_order"` (read-your-writes) and shard
    # pruning via `optimize_skip_unused_shards=1` (sharded by
    # `sipHash64(job_id)`, and the read filters `job_id IN (...)`).
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order", optimize_skip_unused_shards=True)
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(name="job_id"),
        "time_window_start": DateTimeDatabaseField(name="time_window_start"),
        "action_id": IntegerDatabaseField(name="action_id"),
        "count_state": UnknownDatabaseField(name="count_state"),
        "unique_persons_state": UnknownDatabaseField(name="unique_persons_state"),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE()

    def to_printed_hogql(self):
        return "web_goals_preaggregated"
