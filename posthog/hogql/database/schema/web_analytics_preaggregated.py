from posthog.hogql.database.models import (
    DatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    DateDatabaseField,
    Table,
    FieldOrTable,
)


web_preaggregated_base_fields = {
    "team_id": IntegerDatabaseField(name="team_id"),
    "day_bucket": DateDatabaseField(name="day_bucket"),
    "host": StringDatabaseField(name="host", nullable=True),
    "device_type": StringDatabaseField(name="device_type", nullable=True),
}

web_preaggregated_base_aggregation_fields = {
    "persons_uniq_state": DatabaseField(name="persons_uniq_state"),
    "pageviews_count_state": DatabaseField(name="pageviews_count_state"),
    "sessions_uniq_state": DatabaseField(name="sessions_uniq_state"),
}


class WebOverviewDailyTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        "total_session_duration_state": DatabaseField(name="total_session_duration_state"),
        "total_bounces_state": DatabaseField(name="total_bounces_state"),
    }

    def to_printed_clickhouse(self, context):
        return "web_overview_daily"

    def to_printed_hogql(self):
        return "web_overview_daily"


class WebStatsDailyTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        "browser": StringDatabaseField(name="browser", nullable=True),
        "os": StringDatabaseField(name="os", nullable=True),
        "referring_domain": StringDatabaseField(name="referring_domain", nullable=True),
        "viewport": StringDatabaseField(name="viewport", nullable=True),
        "utm_source": StringDatabaseField(name="utm_source", nullable=True),
        "utm_medium": StringDatabaseField(name="utm_medium", nullable=True),
        "utm_campaign": StringDatabaseField(name="utm_campaign", nullable=True),
        "utm_term": StringDatabaseField(name="utm_term", nullable=True),
        "utm_content": StringDatabaseField(name="utm_content", nullable=True),
        "country": StringDatabaseField(name="country", nullable=True),
    }

    def to_printed_clickhouse(self, context):
        return "web_stats_daily"

    def to_printed_hogql(self):
        return "web_stats_daily"


class WebBouncesDailyTable(Table):
    fields: dict[str, FieldOrTable] = {
        **web_preaggregated_base_fields,
        **web_preaggregated_base_aggregation_fields,
        "entry_path": StringDatabaseField(name="entry_path", nullable=True),
        "bounces_count_state": DatabaseField(name="bounces_count_state"),
    }

    def to_printed_clickhouse(self, context):
        return "web_bounces_daily"

    def to_printed_hogql(self):
        return "web_bounces_daily"
