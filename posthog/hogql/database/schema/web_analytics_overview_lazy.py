from posthog.hogql.database.models import (
    DatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
)


class WebAnalyticsOverviewLazyTable(Table):
    """HogQL schema for the `web_analytics_overview_lazy` table.

    Narrow schema — filters are baked into the INSERT WHERE (and therefore the
    cache key via the AST hash), so the table only stores boilerplate columns
    plus the aggregate states that the readback merges.
    """

    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "job_id": StringDatabaseField(name="job_id"),
        "time_window_start": DateTimeDatabaseField(name="time_window_start"),
        "expires_at": DateTimeDatabaseField(name="expires_at"),
        "persons_uniq_state": DatabaseField(name="persons_uniq_state"),
        "sessions_uniq_state": DatabaseField(name="sessions_uniq_state"),
        "pageviews_count_state": DatabaseField(name="pageviews_count_state"),
        "bounces_count_state": DatabaseField(name="bounces_count_state"),
        "total_session_duration_state": DatabaseField(name="total_session_duration_state"),
        "total_session_count_state": DatabaseField(name="total_session_count_state"),
    }

    def to_printed_clickhouse(self, context):
        return "web_analytics_overview_lazy"

    def to_printed_hogql(self):
        return "web_analytics_overview_lazy"
