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

from posthog.clickhouse.preaggregation.web_active_hours_preaggregated_sql import (
    DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE,
)


class WebActiveHoursPreaggregatedTable(Table):
    # `load_balancing="in_order"` matches sibling lazy-precompute tables and is
    # important for read-your-writes: both INSERT (via _get_insert_settings) and
    # SELECT deterministically prefer the same replica, so the read sees data the
    # INSERT just wrote. `optimize_skip_unused_shards=1` adds shard pruning since
    # the read filters by `job_id IN (...)` and the table is sharded by
    # `sipHash64(job_id)`.
    top_level_settings: HogQLQuerySettings | None = Field(
        default_factory=lambda: HogQLQuerySettings(load_balancing="in_order", optimize_skip_unused_shards=True)
    )

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(name="job_id"),
        "time_window_start": DateTimeDatabaseField(name="time_window_start"),
        # Aggregate-state columns are passed straight to `uniqMergeIf` / `sumMergeIf`
        # in the read query. HogQL doesn't need to know their internal shape —
        # `UnknownDatabaseField` is opaque enough.
        "uniq_users_state": UnknownDatabaseField(name="uniq_users_state"),
        "sum_events_state": UnknownDatabaseField(name="sum_events_state"),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_WEB_ACTIVE_HOURS_PREAGGREGATED_TABLE()

    def to_printed_hogql(self):
        return "web_active_hours_preaggregated"
