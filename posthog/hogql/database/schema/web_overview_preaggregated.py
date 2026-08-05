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

from posthog.clickhouse.preaggregation.web_overview_preaggregated_sql import (
    DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE,
)


class WebOverviewPreaggregatedTable(Table):
    description: str = (
        "Pre-aggregated web analytics overview metrics (unique users/sessions, pageviews, session duration, bounce rate) "
        "computed per precompute job, used internally by the web analytics product. Metric columns are "
        "AggregateFunction states that must be merged."
    )
    # `load_balancing="in_order"` matches sibling lazy-precompute tables and is
    # important for read-your-writes: both INSERT (via _get_insert_settings) and
    # SELECT deterministically prefer the same replica, so the read sees data the
    # INSERT just wrote. `optimize_skip_unused_shards=1` adds shard pruning since
    # our combiner filters by `job_id IN (...)` and the table is sharded by
    # `sipHash64(job_id)`.
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
        # Aggregate-state columns are passed straight to `uniqMergeIf`/`sumMergeIf`/`avgMergeIf`
        # in the read query. HogQL doesn't need to know their internal shape —
        # `UnknownDatabaseField` is opaque enough.
        "uniq_users_state": UnknownDatabaseField(
            name="uniq_users_state", description="AggregateFunction(uniq) state for unique users; merge to read."
        ),
        "uniq_sessions_state": UnknownDatabaseField(
            name="uniq_sessions_state", description="AggregateFunction(uniq) state for unique sessions; merge to read."
        ),
        "sum_pageviews_state": UnknownDatabaseField(
            name="sum_pageviews_state", description="AggregateFunction(sum) state for pageview count; merge to read."
        ),
        "avg_duration_state": UnknownDatabaseField(
            name="avg_duration_state",
            description="AggregateFunction(avg) state for session duration in seconds; merge to read.",
        ),
        "avg_bounce_state": UnknownDatabaseField(
            name="avg_bounce_state", description="AggregateFunction(avg) state for bounce rate; merge to read."
        ),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE()

    def to_printed_hogql(self):
        return "web_overview_preaggregated"
