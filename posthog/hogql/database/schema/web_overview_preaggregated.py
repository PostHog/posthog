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
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(name="job_id"),
        "time_window_start": DateTimeDatabaseField(name="time_window_start"),
        # Aggregate-state columns are passed straight to `uniqExactMerge`/`sumMerge`/`avgMerge`
        # in the read query. HogQL doesn't need to know their internal shape — UnknownDatabaseField
        # is opaque enough for that.
        "uniq_users_state": UnknownDatabaseField(name="uniq_users_state"),
        "uniq_sessions_state": UnknownDatabaseField(name="uniq_sessions_state"),
        "sum_pageviews_state": UnknownDatabaseField(name="sum_pageviews_state"),
        "avg_duration_state": UnknownDatabaseField(name="avg_duration_state"),
        "avg_bounce_state": UnknownDatabaseField(name="avg_bounce_state"),
    }

    def to_printed_clickhouse(self, context):
        return DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE()

    def to_printed_hogql(self):
        return "web_overview_preaggregated"
