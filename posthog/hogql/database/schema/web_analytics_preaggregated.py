from posthog.hogql.database.models import (
    IntegerDatabaseField,
    StringDatabaseField,
    DateDatabaseField,
    Table,
    FieldOrTable,
)


class WebOverviewDailyTable(Table):
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id"),
        "day_bucket": DateDatabaseField(name="day_bucket"),
        "host": StringDatabaseField(name="host", nullable=True),
        "device_type": StringDatabaseField(name="device_type", nullable=True),
        "persons_uniq_state": StringDatabaseField(name="persons_uniq_state"),
        "pageviews_count_state": StringDatabaseField(name="pageviews_count_state"),
        "sessions_uniq_state": StringDatabaseField(name="sessions_uniq_state"),
        "total_session_duration_state": StringDatabaseField(name="total_session_duration_state"),
        "total_bounces_state": StringDatabaseField(name="total_bounces_state"),
    }

    def to_printed_clickhouse(self, context):
        return "web_overview_daily"

    def to_printed_hogql(self):
        return "web_overview_daily"
